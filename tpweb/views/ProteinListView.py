from django.views import View
from django.shortcuts import render
from django.db.models import Exists, OuterRef, Prefetch
from django.http import JsonResponse
from django.http import Http404
from django.urls import reverse
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q

from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.ScoreParam import ScoreParamOptions
from tpweb.models.BioentryStructure import BioentryStructure
from django.shortcuts import redirect
from urllib.parse import urlencode, parse_qs
from tpweb.services.protein_list import (
    DEFAULT_PAGE_SIZE,
    add_selected_parameter,
    apply_protein_search,
    apply_selected_parameter_filters,
    empty_pagination_payload,
    grouped_selected_parameters,
    humanize_identifier,
    normalize_selected_parameters,
    parse_page_size,
    remove_selected_parameter,
)
from tpweb.services.protein_formula import (
    NO_FORMULA_SENTINEL,
    build_col_descriptions,
    build_score_dict_and_columns,
    choose_formula,
    coefficient_map,
    formula_to_dto,
    ordered_score_params,
    resolve_formulas_for_user,
)
from tpweb.services.protein_annotations import (
    ANNOTATION_KIND_CONFIG,
    annotation_dbnames,
    annotation_kind_label,
    annotation_supports_prefix,
    annotation_term_name,
    normalize_annotation_kind,
)
from tpweb.services.workspace import (
    get_workspace_session_value,
    set_workspace_session_value,
)
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.protein_serializer import (
    build_protein_table_row,
    compute_score_value,
    score_param_value_map,
)
from tpweb.services.csv_exports import csv_response, xlsx_sections_response
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
)
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)
from tpweb.services.workspace import resolve_workspace_user
from tpweb.models.CustomParamFile import CustomParam
from pathlib import Path
import logging


logger = logging.getLogger(__name__)


class ProteinSearchSuggestionsView(View):
    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            return JsonResponse({"results": []})

        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"results": []})

        try:
            limit = int(request.GET.get("limit", 8))
        except (TypeError, ValueError):
            limit = 8
        limit = max(1, min(limit, 20))

        suggestions = (
            Bioentry.objects.filter(
                biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX
            )
            .filter(
                Q(accession__icontains=query) |
                Q(description__icontains=query)
            )
            .order_by("accession")
            .values("accession", "description")[:limit]
        )

        results = []
        seen_accessions = set()
        for item in suggestions:
            accession = (item.get("accession") or "").strip()
            if not accession or accession in seen_accessions:
                continue
            seen_accessions.add(accession)
            description = (item.get("description") or "").strip()
            if len(description) > 120:
                description = description[:117] + "..."
            results.append({
                "accession": accession,
                "description": description,
            })

        return JsonResponse({"results": results})


class ProteinListView(View):
    template_name = 'search/proteins.html'
    VISIBLE_COLUMNS_SESSION_KEY = "protein_visible_columns"
    FIXED_COLUMN_LABELS = (
        "Protein",
        "Description",
        "Gene",
        "Structure",
        "EC",
        "GO",
        "Score",
    )

    @staticmethod
    def _build_export_url(request):
        params = request.GET.copy()
        if "page" in params:
            params.pop("page")
        params["export"] = "csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=csv"

    @staticmethod
    def _build_view_export_url(request):
        params = request.GET.copy()
        if "page" in params:
            params.pop("page")
        params["export"] = "view_csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=view_csv"

    @staticmethod
    def _build_column_rows(score_params, selected_column_names):
        selected_order = [name for name in selected_column_names if name]
        selected_set = set(selected_order)
        score_param_by_name = {score_param.name: score_param for score_param in score_params}
        ordered_rows = []

        for name in selected_order:
            score_param = score_param_by_name.get(name)
            if score_param is None:
                continue
            ordered_rows.append(
                {
                    "name": name,
                    "label": humanize_identifier(score_param.name) or score_param.name,
                    "category": (score_param.category or "Other").strip() or "Other",
                    "description": score_param.description,
                    "selected": True,
                }
            )

        remaining = sorted(
            [score_param for score_param in score_params if score_param.name not in selected_set],
            key=lambda score_param: (
                (score_param.category or "Other").strip().casefold(),
                (humanize_identifier(score_param.name) or score_param.name).casefold(),
            ),
        )
        for score_param in remaining:
            ordered_rows.append(
                {
                    "name": score_param.name,
                    "label": humanize_identifier(score_param.name) or score_param.name,
                    "category": (score_param.category or "Other").strip() or "Other",
                    "description": score_param.description,
                    "selected": False,
                }
            )
        return ordered_rows

    EC_CLASSES = [
        ("1", "Oxidoreductases"),
        ("2", "Transferases"),
        ("3", "Hydrolases"),
        ("4", "Lyases"),
        ("5", "Isomerases"),
        ("6", "Ligases"),
        ("7", "Translocases"),
    ]

    @staticmethod
    def _build_special_filter_payload(kind, value):
        value = (value or "").strip()
        if not value:
            return None
        if kind == "ec":
            return {
                "id": f"special:ec:{value}",
                "score_param_name": "ec_number",
                "name": value,
                "type": "special",
                "special_key": "ec_filter",
                "special_value": value,
                "display_name": value,
            }
        if kind == "go":
            normalized = value.upper() if not value.upper().startswith("GO:") else value.upper()
            if not normalized.startswith("GO:") and normalized.isdigit():
                normalized = f"GO:{normalized.zfill(7)}"
            return {
                "id": f"special:go:{normalized}",
                "score_param_name": "go_term",
                "name": normalized,
                "type": "special",
                "special_key": "go_filter",
                "special_value": normalized,
                "display_name": normalized,
            }
        return None

    @staticmethod
    def _build_numeric_filter_payload(score_param_id, raw_min, raw_max, operation=None):
        try:
            param_pk = int(score_param_id)
        except (TypeError, ValueError):
            return None
        from tpweb.models.ScoreParam import ScoreParam as _ScoreParam
        try:
            score_param = _ScoreParam.objects.get(pk=param_pk)
        except _ScoreParam.DoesNotExist:
            return None
        try:
            value_min = float(str(raw_min).replace(",", ".")) if raw_min not in ("", None) else None
        except (TypeError, ValueError):
            value_min = None
        try:
            value_max = float(str(raw_max).replace(",", ".")) if raw_max not in ("", None) else None
        except (TypeError, ValueError):
            value_max = None

        requested_operation = str(operation or "").strip().lower()
        operation_map = {
            "gte": ">=",
            ">=": ">=",
            "min": ">=",
            "lte": "<=",
            "<=": "<=",
            "max": "<=",
            "between": "between",
            "range": "between",
        }
        requested_operation = operation_map.get(requested_operation)

        if requested_operation == ">=":
            value_max = None
        elif requested_operation == "<=":
            if value_max is None:
                value_max = value_min
            value_min = None
        elif requested_operation == "between":
            if value_min is None or value_max is None:
                return None

        if value_min is None and value_max is None:
            return None
        if value_min is not None and value_max is not None:
            if value_min > value_max:
                value_min, value_max = value_max, value_min
            operation = "between"
            display_value = f"between {value_min:g} and {value_max:g}"
            filter_id = f"numeric:{score_param.pk}:between:{value_min:g}:{value_max:g}"
            primary_value = value_min
        elif value_min is not None:
            operation = ">="
            display_value = f"≥ {value_min:g}"
            filter_id = f"numeric:{score_param.pk}:>=:{value_min:g}"
            primary_value = value_min
        else:
            operation = "<="
            display_value = f"≤ {value_max:g}"
            filter_id = f"numeric:{score_param.pk}:<=:{value_max:g}"
            primary_value = value_max
            value_max = None
        return {
            "id": filter_id,
            "score_param_id": score_param.pk,
            "score_param_name": score_param.name,
            "type": "numeric",
            "operation": operation,
            "value": primary_value,
            "value_max": value_max if operation == "between" else None,
            "display_name": display_value,
        }

    @staticmethod
    def _build_filter_groups(score_params, selected_parameters, structure_choices=None, function_data=None):
        selected_option_ids = {
            str(parameter.get("id"))
            for parameter in selected_parameters
            if str(parameter.get("type") or "categorical").lower() not in {"numeric", "special"}
        }

        active_numeric_by_param = {}
        for parameter in selected_parameters:
            if str(parameter.get("type") or "").lower() != "numeric":
                continue
            param_id = parameter.get("score_param_id")
            if param_id in ("", None):
                continue
            param_id = str(param_id)
            active_numeric_by_param.setdefault(param_id, []).append(parameter)

        grouped = {}
        numeric_param_count = 0
        for score_param in score_params:
            type_code = (score_param.type or "").upper()
            is_categorical = type_code.startswith("C") or type_code == "CATEGORICAL"
            category = (score_param.category or "Other").strip() or "Other"
            param_label = humanize_identifier(score_param.name) or score_param.name

            if not is_categorical:
                numeric_param_count += 1
                active_filters = active_numeric_by_param.get(str(score_param.pk), [])
                grouped.setdefault(category, []).append({
                    "id": score_param.pk,
                    "name": score_param.name,
                    "label": param_label,
                    "description": score_param.description or "",
                    "type": "numeric",
                    "active_filters": [
                        {
                            "id": entry.get("id"),
                            "display_name": entry.get("display_name", ""),
                        }
                        for entry in active_filters
                    ],
                    "any_active": bool(active_filters),
                    "search_text": (param_label + " " + category).lower(),
                })
                continue
            choices = list(score_param.choices.all())
            if not choices:
                continue
            options = []
            search_tokens = [param_label, category]
            any_active = False
            for option in choices:
                option_label = humanize_identifier(option.name) or option.name
                option_active = str(option.pk) in selected_option_ids
                if option_active:
                    any_active = True
                option_tone = ""
                if score_param.name in {"human_offtarget", "gut_microbiome_offtarget"}:
                    normalized_option_name = str(option.name or "").strip().lower()
                    if normalized_option_name in {"hit", "y", "yes"}:
                        option_tone = "risk"
                    elif normalized_option_name in {"no_hit", "no hit", "n", "no"}:
                        option_tone = "favorable"
                options.append({
                    "id": option.pk,
                    "name": option.name,
                    "label": option_label,
                    "description": option.description or "",
                    "active": option_active,
                    "tone": option_tone,
                })
                search_tokens.append(option_label)
            grouped.setdefault(category, []).append({
                "id": score_param.pk,
                "name": score_param.name,
                "label": param_label,
                "description": score_param.description or "",
                "type": "categorical",
                "options": options,
                "any_active": any_active,
                "search_text": " ".join(search_tokens).lower(),
            })

        preferred_order = [
            "Pocket",
            "Off-target",
            "Essentiality",
            "Localization",
            "Protein",
            "Custom",
            "Other",
        ]

        def _category_sort_key(category):
            try:
                return (preferred_order.index(category), "")
            except ValueError:
                return (len(preferred_order), category.casefold())

        preferred_param_order = {
            "Pocket": {
                "Druggability": 0,
                "druggability": 0,
            },
            "Off-target": {
                "human_offtarget": 0,
                "gut_microbiome_offtarget": 1,
                "human_identity": 2,
                "human_evalue": 3,
            },
            "Essentiality": {
                "hit_in_deg": 0,
                "deg_identity": 1,
                "deg_evalue": 2,
            },
            "Localization": {
                "Localization": 0,
            },
        }

        def _param_sort_key(category, entry):
            category_order = preferred_param_order.get(category, {})
            name = entry.get("name", "")
            return (category_order.get(name, 100), entry["label"].casefold())

        filter_groups = []

        function_data = function_data or {}
        ec_classes = function_data.get("ec_classes") or []
        ec_specific_active = function_data.get("ec_specific_active") or []
        go_active = function_data.get("go_active") or []
        ec_explorer_url = function_data.get("ec_explorer_url", "")
        if ec_classes or ec_specific_active or go_active or ec_explorer_url:
            any_function_active = (
                any(cls.get("active") for cls in ec_classes)
                or bool(ec_specific_active)
                or bool(go_active)
            )
            filter_groups.append({
                "category": "Function",
                "is_function": True,
                "ec_classes": ec_classes,
                "ec_specific_active": ec_specific_active,
                "go_active": go_active,
                "ec_explorer_url": ec_explorer_url,
                "any_active": any_function_active,
                "param_count": len(ec_specific_active) + len(go_active) + sum(1 for c in ec_classes if c.get("active")),
            })

        structure_choices = [choice for choice in (structure_choices or []) if choice.get("value")]
        if structure_choices:
            active_structure = next((choice for choice in structure_choices if choice.get("active")), None)
            filter_groups.append({
                "category": "Structure",
                "params": [{
                    "id": "structure_source",
                    "name": "structure_source",
                    "label": "Structure source",
                    "description": "Limit proteins by the type of structure evidence currently available.",
                    "options": [
                        {
                            "id": f"structure::{choice['value']}",
                            "name": choice["value"],
                            "label": choice["label"],
                            "description": "",
                            "active": bool(choice.get("active")),
                            "url": choice["url"],
                            "is_link": True,
                        }
                        for choice in structure_choices
                    ],
                    "any_active": bool(active_structure),
                    "search_text": "structure source " + " ".join(
                        choice["label"] for choice in structure_choices
                    ).lower(),
                }],
                "any_active": bool(active_structure),
                "param_count": 1,
            })

        for category in sorted(grouped.keys(), key=_category_sort_key):
            params = sorted(grouped[category], key=lambda entry: _param_sort_key(category, entry))
            filter_groups.append({
                "category": category,
                "params": params,
                "any_active": any(entry["any_active"] for entry in params),
                "param_count": len(params),
            })
        return filter_groups, numeric_param_count

    @staticmethod
    def _build_clear_search_url(request, page_size):
        params = request.GET.copy()
        params["pageSize"] = page_size
        for key in ("search", "page"):
            if key in params:
                params.pop(key)
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?"

    @staticmethod
    def _build_clear_annotation_url(request, page_size):
        params = request.GET.copy()
        params["pageSize"] = page_size
        for key in ("annotation_kind", "annotation_value", "ec_filter", "page"):
            if key in params:
                params.pop(key)
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?"

    @staticmethod
    def _build_sort_url(request, col, current_sort_col, current_sort_dir, default_dir="desc"):
        params = request.GET.copy()
        params["sort_col"] = col
        if col == current_sort_col:
            params["sort_dir"] = "asc" if current_sort_dir == "desc" else "desc"
        else:
            params["sort_dir"] = default_dir
        if "page" in params:
            params.pop("page")
        return f"?{params.urlencode()}"

    @staticmethod
    def _build_clear_structure_url(request, page_size):
        params = request.GET.copy()
        params["pageSize"] = page_size
        for key in ("structure_source", "page"):
            if key in params:
                params.pop(key)
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?"

    @staticmethod
    def _build_structure_source_choices(request, page_size, current_value):
        base_choices = [
            {"value": "experimental", "label": "Has experimental PDB"},
            {"value": "alphafold", "label": "AlphaFold"},
            {"value": "colabfold", "label": "ColabFold"},
            {"value": "none", "label": "No structure"},
        ]
        choices = []
        for choice in base_choices:
            params = request.GET.copy()
            params["pageSize"] = page_size
            params["structure_source"] = choice["value"]
            if "page" in params:
                params.pop("page")
            choices.append({
                **choice,
                "active": current_value == choice["value"],
                "url": f"?{params.urlencode()}",
            })
        return choices

    @staticmethod
    def _build_page_numbers(current_page, total_pages):
        if total_pages <= 9:
            return list(range(1, total_pages + 1))

        pages = [1]
        start = max(2, current_page - 2)
        end = min(total_pages - 1, current_page + 2)

        if start > 2:
            pages.append(None)
        pages.extend(range(start, end + 1))
        if end < total_pages - 1:
            pages.append(None)
        pages.append(total_pages)
        return pages

    @staticmethod
    def _build_table_rows(assembly_name, protein_ids, needed_score_param_names, col_descriptions,
                          coefficient_by_param, expression=None, zero_cache=None):
        if not protein_ids:
            return [], {}

        spv_qs = ScoreParamValue.objects.select_related("score_param")
        if needed_score_param_names is not None:
            spv_qs = spv_qs.filter(score_param__name__in=needed_score_param_names)

        proteins_queryset = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            bioentry_id__in=protein_ids,
        ).prefetch_related(
            "qualifiers__term",
            "structures__pdb",
            "dbxrefs__dbxref__terms__term",
            Prefetch("score_params", queryset=spv_qs),
        )

        proteins_map = {
            protein.bioentry_id: protein for protein in proteins_queryset
        }
        proteins_dto = []
        tdatas = {}
        for protein_id in protein_ids:
            protein = proteins_map.get(protein_id)
            if protein is None:
                continue
            protein_dto, tdata, _ = build_protein_table_row(
                protein,
                visible_columns=col_descriptions,
                coefficient_by_param=coefficient_by_param,
                expression=expression,
                zero_cache=zero_cache,
            )
            tdatas[protein.bioentry_id] = tdata
            proteins_dto.append(protein_dto)

        return proteins_dto, tdatas

    @staticmethod
    def _view_export_sections(
        assembly_name,
        biodb_description,
        formula,
        current_formula,
        search_query,
        grouped_parameters,
        structure_source,
        annotation_filter,
        fixed_column_labels,
        tcolumns,
        rows,
        total_count,
    ):
        filters_text = []
        for score_param, values in grouped_parameters.items():
            filters_text.append(f"{score_param}: {values}")

        if structure_source:
            filters_text.append(f"Structure filter: {humanize_identifier(structure_source)}")

        if annotation_filter:
            label = annotation_filter.get("kind_label") or annotation_filter.get("kind") or "Annotation"
            value = annotation_filter.get("value") or "-"
            filters_text.append(f"{label}: {value}")

        view_rows = [
            ["Genome accession", display_genome_name(assembly_name)],
            ["Genome description", biodb_description or "-"],
            ["Scoring formula", formula.name if formula else "None"],
            ["Formula expression", current_formula or "-"],
            ["Search query", search_query or "-"],
            ["Active filters", " | ".join(filters_text) if filters_text else "None"],
            ["Visible columns", ", ".join(dict.fromkeys([*fixed_column_labels, *tcolumns]))],
            ["Exported proteins", total_count],
        ]

        data_headers = ["Rank", "Protein", "Description", "Gene", "Structure", "EC", "GO"] + list(tcolumns)

        return [
            {
                "title": "Current view",
                "headers": ["Field", "Value"],
                "rows": view_rows,
            },
            {
                "title": "Protein table",
                "headers": data_headers,
                "rows": rows,
            },
        ]

    def post(self, request, genome, *args, **kwargs):
        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )

        action = request.POST.get("action")

        if action == "add_filter":
            option_id = request.POST.get("filter_option_id")
            if option_id:
                try:
                    option_dict = ScoreParamOptions.objects.get(id=option_id).to_dict()
                    selected_parameters = add_selected_parameter(
                        selected_parameters, option_dict
                    )
                except (ScoreParamOptions.DoesNotExist, ValueError, TypeError):
                    pass

        elif action == "add_special_filter":
            kind = (request.POST.get("special_kind") or "").strip().lower()
            value = (request.POST.get("special_value") or "").strip()
            payload = self._build_special_filter_payload(kind, value)
            if payload:
                selected_parameters = add_selected_parameter(selected_parameters, payload)

        elif action == "add_numeric_filter":
            score_param_id = (request.POST.get("score_param_id") or "").strip()
            numeric_operation = (request.POST.get("numeric_operation") or "").strip()
            raw_min = (request.POST.get("value") or "").strip()
            raw_max = (request.POST.get("value_max") or "").strip()
            payload = self._build_numeric_filter_payload(
                score_param_id,
                raw_min,
                raw_max,
                operation=numeric_operation,
            )
            if payload:
                selected_parameters = add_selected_parameter(selected_parameters, payload)

        elif action == "remove_filter":
            option_id = request.POST.get("filter_option_id")
            if option_id:
                selected_parameters = remove_selected_parameter(
                    selected_parameters, option_id
                )

        elif action == "reset_filters":
            selected_parameters = []

        elif action == "update_columns":
            requested_columns = request.POST.getlist("visible_columns")
            requested_columns = [value.strip() for value in requested_columns if value.strip()]
            set_workspace_session_value(
                request.session,
                request.user,
                self.VISIBLE_COLUMNS_SESSION_KEY,
                requested_columns,
            )

        elif action == "reset_columns":
            set_workspace_session_value(
                request.session,
                request.user,
                self.VISIBLE_COLUMNS_SESSION_KEY,
                None,
            )

        set_workspace_session_value(
            request.session, request.user, "selected_parameters", selected_parameters
        )

        return_query = request.POST.get("return_query", "").strip()
        redirect_url = request.path
        if return_query:
            params = parse_qs(return_query, keep_blank_values=False)
            if action == "reset_filters":
                for key in ("annotation_kind", "annotation_value", "ec_filter", "structure_source"):
                    params.pop(key, None)
            cleaned = urlencode(
                {k: v[0] if len(v) == 1 else v for k, v in params.items()},
                doseq=True,
            )
            if cleaned:
                redirect_url = f"{redirect_url}?{cleaned}"
        return redirect(redirect_url)

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        page_size = parse_page_size(request.GET.get("pageSize", DEFAULT_PAGE_SIZE))
        clear_search_url = self._build_clear_search_url(request, page_size)
        formulas = resolve_formulas_for_user(request.user)
        requested_formula = request.GET.get("scoreformula", NO_FORMULA_SENTINEL)
        formula = choose_formula(formulas, requested_formula)

        bdb = Biodatabase.objects.get(name=assembly_name)
        #ScoreParam.initialize()
        #formula = ScoreFormula.objects.filter(name="GARDP_Target_Overall").get()
        #formula = ScoreFormula.objects.filter(name="GARDP_Virtual_Screening").get()

        if formula is None:
            formula_term_list = []
            col_descriptions = {}
            formuladto = None
            current_formula = ""
        else:
            formula_term_list = list(
                formula.terms.select_related("score_param").prefetch_related("score_param__choices")
            )
            col_descriptions = build_col_descriptions(formula_term_list)
            formuladto = formula_to_dto(formula, col_descriptions)
            current_formula = formula.get_current_formula()

        current_formula_pk = getattr(formula, "pk", None)
        workspace_user_for_drawer = resolve_workspace_user(request.user)
        formulas_for_drawer = []
        for f in formulas:
            formulas_for_drawer.append({
                "pk": f.pk,
                "name": f.name,
                "is_default": bool(f.default),
                "is_current": f.pk == current_formula_pk,
                "expression": f.get_current_formula(),
                "is_user_formula": f.user_id is not None and f.user_id == getattr(workspace_user_for_drawer, "pk", None),
            })

        workspace_user = resolve_workspace_user(request.user)
        custom_data_files = list(
            CustomParam.objects.filter(owner=workspace_user, accession=assembly_name).order_by("tsv")
        )
        custom_data_for_drawer = [
            {"file_name": Path(cp.tsv.name).name}
            for cp in custom_data_files
        ]

        all_visible_score_params = list(
            visible_score_params_queryset(request.user).prefetch_related("choices")
        )
        visible_score_param_by_name = {
            score_param.name: score_param for score_param in all_visible_score_params
        }
        default_column_names = [score_param.name for score_param in ordered_score_params(formula_term_list)]
        if not default_column_names:
            # No formula active — default to Druggability column if it exists
            default_column_names = [
                name for name in [
                    "Druggability",
                    "human_offtarget",
                    "human_identity",
                    "human_evalue",
                ]
                if name in visible_score_param_by_name
            ]
        stored_column_names = get_workspace_session_value(
            request.session,
            request.user,
            self.VISIBLE_COLUMNS_SESSION_KEY,
            None,
        )
        if stored_column_names is None:
            selected_column_names = default_column_names
        else:
            selected_column_names = [
                name for name in stored_column_names if name in visible_score_param_by_name
            ]
        ordered_params = [
            visible_score_param_by_name[name]
            for name in selected_column_names
            if name in visible_score_param_by_name
        ]
        score_dict, tcolumns = build_score_dict_and_columns(ordered_params)
        selected_col_descriptions = {
            score_param.name: (score_param.description or "")
            for score_param in ordered_params
        }
        if "Score" in tcolumns:
            selected_col_descriptions["Score"] = "Weighted prioritization score from the selected formula."
        col_descriptions = {
            **selected_col_descriptions,
            **col_descriptions,
        }

        if formula is None:
            tcolumns = [c for c in tcolumns if c != "Score"]

        tdatas = {}
        page = request.GET.get('page', 1)
        search_query = request.GET.get('search', '').strip()
        raw_sort_col = request.GET.get("sort_col", "").strip()
        raw_sort_dir = request.GET.get("sort_dir", "").strip().lower()
        if raw_sort_dir not in ("asc", "desc"):
            raw_sort_dir = ""
        structure_source = request.GET.get("structure_source", "").strip().lower()
        ec_filter_value = request.GET.get("ec_filter", "").strip()
        annotation_kind = normalize_annotation_kind(request.GET.get("annotation_kind", "ec"))
        annotation_value = request.GET.get("annotation_value", "").strip()
        if ec_filter_value:
            annotation_kind = "ec"
            annotation_value = ec_filter_value
        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
        )
        if structure_source == "none":
            proteins = proteins.filter(structures__isnull=True)
        elif structure_source == "experimental":
            experimental_structures = BioentryStructure.objects.filter(
                bioentry=OuterRef("pk"),
            ).exclude(
                pdb__experiment__in=PDB_MODEL_EXPERIMENTS,
            )
            proteins = proteins.annotate(
                has_experimental_structure=Exists(experimental_structures),
            ).filter(has_experimental_structure=True)
        elif structure_source == "alphafold":
            proteins = proteins.filter(structures__pdb__experiment=PDB_EXPERIMENT_ALPHAFOLD)
        elif structure_source == "colabfold":
            proteins = proteins.filter(structures__pdb__experiment=PDB_EXPERIMENT_COLABFOLD)

        if annotation_value:
            annotation_query = {
                "dbxrefs__dbxref__dbname__in": annotation_dbnames(annotation_kind),
            }
            lookup_name = (
                "dbxrefs__dbxref__accession__istartswith"
                if annotation_supports_prefix(annotation_kind)
                else "dbxrefs__dbxref__accession__iexact"
            )
            annotation_query[lookup_name] = annotation_value
            proteins = proteins.filter(**annotation_query)

        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )
        grouped_parameters = grouped_selected_parameters(selected_parameters, humanize=True)
        display_parameters = [
            {
                **parameter,
                "display_score_param_name": (
                    humanize_identifier(parameter.get("score_param_name")) or parameter.get("score_param_name")
                ),
                "name": parameter.get("name") or parameter.get("display_name") or "",
                "display_name": (
                    parameter.get("display_name")
                    if str(parameter.get("type") or "").lower() in {"numeric", "special"}
                    else (humanize_identifier(parameter.get("name")) or parameter.get("name"))
                ),
            }
            for parameter in selected_parameters
        ]

        if selected_parameters:
            try:
                proteins = apply_selected_parameter_filters(proteins, selected_parameters)
            except Exception:
                logger.exception("Failed to build protein selected-parameter filters: %s", selected_parameters)
                raise

        proteins = apply_protein_search(proteins, search_query)

        formula_expression = getattr(formula, "expression", "") or ""
        formula_param_names = {term.score_param.name for term in formula_term_list}
        column_param_names = set(selected_column_names)
        # Include sort column in prefetch when it's a score param column
        sort_param_for_prefetch = raw_sort_col if raw_sort_col in selected_column_names else None
        if formula_expression:
            from tpweb.services.formula_evaluator import (
                build_all_options_zero, build_expression_variables, safe_eval_expression,
            )
            zero_cache = build_all_options_zero(request.user)
            needed_score_param_names = None  # prefetch all for expression scoring
        else:
            zero_cache = None
            needed_score_param_names = formula_param_names | column_param_names
            if sort_param_for_prefetch:
                needed_score_param_names = needed_score_param_names | {sort_param_for_prefetch}

        ranking_spv_qs = ScoreParamValue.objects.select_related("score_param")
        if needed_score_param_names is not None:
            ranking_spv_qs = ranking_spv_qs.filter(score_param__name__in=needed_score_param_names)

        ranking_queryset = proteins.only(
            "bioentry_id",
            "accession",
            "name",
            "description",
        ).prefetch_related(
            Prefetch("score_params", queryset=ranking_spv_qs)
        ).distinct()

        coefficient_by_param = coefficient_map(formula_term_list)

        # Resolve effective sort: which column and direction
        # When no formula and no explicit sort, default to Druggability desc if available
        _drugg_default = (
            not raw_sort_col and formula is None
            and "Druggability" in selected_column_names
        )
        sort_by_param = raw_sort_col if raw_sort_col in selected_column_names else (
            "Druggability" if _drugg_default else None
        )
        sort_by_score = (raw_sort_col == "Score" and formula is not None) or (
            not raw_sort_col and formula is not None and not sort_by_param
        )
        sort_by_accession = not sort_by_param and not sort_by_score
        effective_sort_col = sort_by_param or ("Score" if sort_by_score else "__accession__")
        effective_sort_dir = raw_sort_dir or ("asc" if sort_by_accession else "desc")

        ranked_proteins = []
        try:
            for protein in ranking_queryset:
                param_values = score_param_value_map(protein)
                if formula_expression and zero_cache is not None:
                    variables = build_expression_variables(protein, zero_cache)
                    try:
                        score_value = float(safe_eval_expression(formula_expression, variables))
                    except (ValueError, ZeroDivisionError, OverflowError):
                        score_value = 0.0
                else:
                    score_value, _ = compute_score_value(param_values, coefficient_by_param)
                ranked_proteins.append(
                    {
                        "id": protein.bioentry_id,
                        "accession": protein.accession,
                        "score": score_value,
                        "col_val": param_values.get(sort_by_param) if sort_by_param else None,
                    }
                )
        except Exception:
            logger.exception(
                "Failed to evaluate protein ranking. selected_parameters=%s sort_col=%s sort_dir=%s needed_score_param_names=%s",
                selected_parameters,
                effective_sort_col,
                effective_sort_dir,
                sorted(needed_score_param_names) if needed_score_param_names is not None else "all",
            )
            raise

        if sort_by_param:
            is_desc = effective_sort_dir == "desc"
            non_null, null_group = [], []
            for p in ranked_proteins:
                v = p["col_val"]
                if v is None or str(v).strip() in ("", "-"):
                    null_group.append(p)
                else:
                    non_null.append(p)
            sample = non_null[0]["col_val"] if non_null else None
            is_numeric_sort = False
            if sample is not None:
                try:
                    float(str(sample).replace(",", "."))
                    is_numeric_sort = True
                except (ValueError, TypeError):
                    pass
            if is_numeric_sort:
                non_null.sort(
                    key=lambda p: (float(str(p["col_val"]).replace(",", ".")), p["accession"]),
                    reverse=is_desc,
                )
            else:
                non_null.sort(
                    key=lambda p: (str(p["col_val"]).casefold(), p["accession"]),
                    reverse=is_desc,
                )
            ranked_proteins = non_null + null_group
        elif sort_by_score:
            if effective_sort_dir == "asc":
                ranked_proteins = sorted(ranked_proteins, key=lambda p: (p["score"], p["accession"]))
            else:
                ranked_proteins = sorted(ranked_proteins, key=lambda p: (-p["score"], p["accession"]))
        else:
            ranked_proteins = sorted(ranked_proteins, key=lambda p: p["accession"],
                                     reverse=(effective_sort_dir == "desc"))

        export_mode = request.GET.get("export")
        if export_mode in {"csv", "view_csv"}:
            export_ids = [protein["id"] for protein in ranked_proteins]
            export_proteins, export_tdatas = self._build_table_rows(
                assembly_name,
                export_ids,
                needed_score_param_names,
                col_descriptions,
                coefficient_by_param,
                expression=formula_expression or None,
                zero_cache=zero_cache,
            )
            headers = ["Rank", "Protein", "Description", "Gene", "Structure", "EC", "GO"] + tcolumns
            rows = []
            for index, protein in enumerate(export_proteins, start=1):
                metric_values = export_tdatas.get(protein["id"], {})
                rows.append(
                    [
                        index,
                        protein["accession"],
                        protein["description"],
                        protein.get("genes_text") or "-",
                        protein["structure_source_label"],
                        protein.get("ec_text") or "-",
                        protein.get("go_text") or "-",
                        *[metric_values.get(column, "-") for column in tcolumns],
                    ]
                )
            if export_mode == "view_csv":
                sections = self._view_export_sections(
                    assembly_name=assembly_name,
                    biodb_description=bdb.description if bdb.description else "",
                    formula=formula,
                    current_formula=current_formula,
                    search_query=search_query,
                    grouped_parameters=grouped_parameters,
                    structure_source=structure_source,
                    annotation_filter={
                        "kind": annotation_kind,
                        "kind_label": annotation_kind_label(annotation_kind),
                        "value": annotation_value,
                    } if annotation_value else None,
                    fixed_column_labels=self.FIXED_COLUMN_LABELS,
                    tcolumns=tcolumns,
                    rows=rows,
                    total_count=len(rows),
                )
                return xlsx_sections_response(
                    f"{display_genome_name(assembly_name)}-protein-view",
                    sections,
                )

            return csv_response(
                f"{display_genome_name(assembly_name)}-proteins",
                headers,
                rows,
            )

        paginator = Paginator(ranked_proteins, page_size)
        try:
            proteins_page = paginator.page(page)
        except PageNotAnInteger:
            proteins_page = paginator.page(1)
        except EmptyPage:
            proteins_page = paginator.page(max(1, paginator.num_pages))

        proteins_ids_paginated = [protein["id"] for protein in proteins_page.object_list]

        proteins_dto, tdatas = self._build_table_rows(
            assembly_name,
            proteins_ids_paginated,
            needed_score_param_names,
            col_descriptions,
            coefficient_by_param,
            expression=formula_expression or None,
            zero_cache=zero_cache,
        )
        page_tdatas = {pid: tdatas.get(pid, {}) for pid in proteins_ids_paginated}

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        query_string = query_params.urlencode()

        structure_source_choices = self._build_structure_source_choices(
            request, page_size, structure_source
        )

        active_ec_values = []
        active_go_values = []
        for parameter in selected_parameters:
            if str(parameter.get("type") or "").lower() != "special":
                continue
            special_key = parameter.get("special_key")
            special_value = parameter.get("special_value")
            entry_id = parameter.get("id")
            if special_key == "ec_filter" and special_value:
                active_ec_values.append({"value": special_value, "id": entry_id})
            elif special_key == "go_filter" and special_value:
                active_go_values.append({"value": special_value, "id": entry_id})

        ec_class_value_set = {value for value, _ in self.EC_CLASSES}
        active_ec_class_set = {entry["value"] for entry in active_ec_values if entry["value"] in ec_class_value_set}
        ec_specific_active = [entry for entry in active_ec_values if entry["value"] not in ec_class_value_set]

        ec_classes_for_drawer = [
            {
                "value": value,
                "label": f"{value} · {label}",
                "short_label": value,
                "name": label,
                "active": value in active_ec_class_set,
            }
            for value, label in self.EC_CLASSES
        ]

        function_data = {
            "ec_classes": ec_classes_for_drawer,
            "ec_specific_active": ec_specific_active,
            "go_active": active_go_values,
            "ec_explorer_url": reverse(
                "tpwebapp:annotation_explorer",
                kwargs={"genome": genome_url_slug(assembly_name), "annotation_kind": "ec"},
            ),
        }

        filter_groups, numeric_param_count = self._build_filter_groups(
            all_visible_score_params,
            selected_parameters,
            structure_choices=structure_source_choices,
            function_data=function_data,
        )

        # Pagination info
        pagination_info = {
            'proteins': proteins_page,
            'has_previous': proteins_page.has_previous(),
            'has_next': proteins_page.has_next(),
            'previous_page_number': proteins_page.previous_page_number() if proteins_page.has_previous() else None,
            'next_page_number': proteins_page.next_page_number() if proteins_page.has_next() else None,
            'number': proteins_page.number,
            'num_pages': proteins_page.paginator.num_pages,
            'page_range': proteins_page.paginator.page_range
        }
        page_numbers = self._build_page_numbers(proteins_page.number, proteins_page.paginator.num_pages)
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), bdb.name
        )
        annotation_filter = {
            "kind": annotation_kind,
            "kind_label": annotation_kind_label(annotation_kind),
            "value": annotation_value,
            "name": annotation_term_name(annotation_kind, annotation_value),
        } if annotation_value else None
        structure_filter = next(
            (choice for choice in structure_source_choices if choice.get("active")),
            None,
        )

        sort_col_urls = {
            "__accession__": self._build_sort_url(request, "__accession__", effective_sort_col, effective_sort_dir, default_dir="asc"),
        }
        if formula is not None:
            sort_col_urls["Score"] = self._build_sort_url(request, "Score", effective_sort_col, effective_sort_dir, default_dir="desc")
        for _col in tcolumns:
            if _col == "Score":
                continue
            sort_col_urls[_col] = self._build_sort_url(request, _col, effective_sort_col, effective_sort_dir, default_dir="desc")

        sort_label_by_col = {"__accession__": "Protein"}
        sort_label_by_col.update({col: humanize_identifier(col) or col for col in tcolumns})
        sort_direction_label = "ascending" if effective_sort_dir == "asc" else "descending"
        sorted_by_label = f"{sort_label_by_col.get(effective_sort_col, effective_sort_col)} ({sort_direction_label})"

        return render(request, self.template_name, {
            "biodb__name": bdb.description if bdb.description else bdb.name,
            "biodb_accession": display_genome_name(bdb.name),
            "biodb_description": bdb.description if bdb.description else "",
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": genome_url_slug(assembly_name)}),
            "proteins": proteins_dto,
            "score_dict": score_dict,
            "tcolumns": tcolumns,
            "tdata": page_tdatas,
            "formula": formuladto,
            "col_descriptions": col_descriptions,
            "formulas":formulas,
            "formulas_for_drawer": formulas_for_drawer,
            "custom_data_for_drawer": custom_data_for_drawer,
            "custom_data_count": len(custom_data_for_drawer),
            "custom_score_url": reverse("tpwebapp:formula_form", kwargs={"genome": genome_url_slug(assembly_name)}),
            "custom_data_url": reverse("tpwebapp:customparam", kwargs={"genome": genome_url_slug(assembly_name)}),
            "current_formula":current_formula,
            "formula_term_count": len(formula_term_list),
            "query_string": query_string,
            "genome": genome_url_slug(assembly_name),
            "assembly_name":assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "parameters":selected_parameters,
            "selection_criteria_count": (
                len(selected_parameters)
                + (1 if annotation_value else 0)
                + (1 if structure_filter else 0)
            ),
            "display_parameters":display_parameters,
            "grouped_parameters":grouped_parameters,
            "pagination":pagination_info,
            "page_size": page_size,
            "search_query": search_query,
            "page_numbers": page_numbers,
            "filter_groups": filter_groups,
            "filter_groups_total_options": sum(
                len(param.get("options", []))
                for group in filter_groups
                for param in group.get("params", [])
            ),
            "numeric_param_count": numeric_param_count,
            "pipeline_status": pipeline_status,
            "clear_search_url": clear_search_url,
            "clear_annotation_url": self._build_clear_annotation_url(request, page_size),
            "clear_structure_url": self._build_clear_structure_url(request, page_size),
            "structure_source": structure_source,
            "structure_filter": structure_filter,
            "structure_source_choices": structure_source_choices,
            "ec_filter_value": annotation_value if annotation_kind == "ec" else "",
            "annotation_filter": annotation_filter,
            "column_rows": self._build_column_rows(all_visible_score_params, selected_column_names),
            "selected_column_names": selected_column_names,
            "selected_column_count": len(selected_column_names),
            "default_column_names": default_column_names,
            "fixed_column_labels": [
                label for label in self.FIXED_COLUMN_LABELS
                if label != "Score" or formula is not None
            ],
            "export_url": self._build_export_url(request),
            "view_export_url": self._build_view_export_url(request),
            "sort_col": effective_sort_col,
            "sort_dir": effective_sort_dir,
            "sort_col_urls": sort_col_urls,
            "sorted_by_label": sorted_by_label,
            "formula_active": formula is not None,

        })  # , {'form': form})

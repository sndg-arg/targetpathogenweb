from django.contrib import messages
from django.views import View
from django.shortcuts import render
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from bioseq.models.BioentryQualifierValue import BioentryQualifierValue
from django.http import JsonResponse
from django.http import Http404
from django.urls import reverse
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.BioentryStructure import BioentryStructure
from django.shortcuts import redirect
from urllib.parse import urlencode, parse_qs
from tpweb.services.protein_list import (
    DEFAULT_PAGE_SIZE,
    apply_filter_changes,
    apply_protein_search,
    apply_selected_parameter_filters,
    decode_selected_parameters_param,
    encode_selected_parameters,
    filter_visible_selected_parameters,
    grouped_selected_parameters,
    humanize_identifier,
    normalize_selected_parameters,
    parse_page_size,
)
from tpweb.services.score_param_types import is_categorical_score_param
from tpweb.services.protein_formula import (
    NO_FORMULA_SENTINEL,
    annotate_formula_terms,
    build_all_term_descriptions,
    build_col_descriptions,
    build_score_dict_and_columns,
    choose_formula,
    coefficient_map,
    formula_to_dto,
    ordered_score_params,
    resolve_formulas_for_user,
)
from tpweb.services.protein_annotations import (
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
from tpweb.services.csv_exports import (
    build_export_url,
    build_view_export_url,
    csv_response,
    xlsx_sections_response,
)
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
)
from tpweb.services.formula_evaluator import (
    build_all_options_zero,
    build_expression_variables,
    safe_eval_expression,
)
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)
from tpweb.services.workspace import resolve_workspace_user
from tpweb.models.CustomParamFile import CustomParam
from tpweb.models.FilterPreset import FilterPreset
from pathlib import Path
import json
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
            Bioentry.objects.filter(biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX)
            .filter(
                Q(accession__icontains=query)
                | Q(description__icontains=query)
                | Q(qualifiers__value__icontains=query, qualifiers__term__identifier="gene")
            )
            .distinct()
            .order_by("accession")
            .values("bioentry_id", "accession", "description")[:limit]
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
            results.append(
                {
                    "accession": accession,
                    "description": description,
                    "gene": "",
                    "url": reverse("tpwebapp:protein", kwargs={"protein_id": item["bioentry_id"]}),
                }
            )

        if results:
            gene_map = dict(
                BioentryQualifierValue.objects.filter(
                    bioentry__biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
                    bioentry__accession__in=[r["accession"] for r in results],
                    term__identifier="gene",
                ).values_list("bioentry__accession", "value")
            )
            for r in results:
                r["gene"] = gene_map.get(r["accession"], "")

        return JsonResponse({"results": results})


class ProteinAdvancedFiltersView(View):
    """Standalone "Advanced filters" builder page: lets a user group filter
    conditions into named ALL/ANY blocks (e.g. "druggable by FPocket OR by
    P2Rank"), instead of the plain filter panel's implicit AND-everything.
    Writes tagged entries into the same selected_parameters session list the
    plain panel reads/writes (see apply_selected_parameter_filters's
    group_id/group_mode handling in tpweb/services/protein_list.py), so both
    views -- and the protein list's active-filter chips -- stay in sync.
    Only exposes categorical/numeric score-param conditions (not the special
    EC/GO/ligand/pathway filters), matching what apply_selected_parameter_
    filters's OR-combination (_condition_q) actually supports today."""

    template_name = "search/advanced_filters.html"
    GROUP_ID_PREFIX = "adv:"

    @classmethod
    def _param_options(cls, user):
        options = []
        for score_param in visible_score_params_queryset(user).prefetch_related("choices"):
            # Same exclusion the plain filter panel applies (_build_filter_groups) --
            # these are per-pocket-instance categorical params (e.g. "FPocket #12"),
            # not something worth OR/AND-combining in a general-purpose builder.
            param_name_lower = score_param.name.lower()
            if param_name_lower.endswith("_structure") or param_name_lower.endswith("_pocket"):
                continue
            label = humanize_identifier(score_param.name) or score_param.name
            category = (score_param.category or "Other").strip() or "Other"
            if is_categorical_score_param(score_param):
                choices = [
                    {"id": choice.pk, "label": humanize_identifier(choice.name) or choice.name}
                    for choice in score_param.choices.all()
                ]
                if not choices:
                    continue
                options.append(
                    {
                        "id": score_param.pk,
                        "label": label,
                        "category": category,
                        "type": "categorical",
                        "options": choices,
                    }
                )
            else:
                options.append(
                    {"id": score_param.pk, "label": label, "category": category, "type": "numeric"}
                )
        return options

    @classmethod
    def _existing_groups(cls, selected_parameters, visible_param_ids=None):
        """Reconstruct the builder's group list from session state, for
        re-opening the page with prior advanced groups still shown. Ignores
        entries not tagged by this view (the plain panel's own filters).

        A condition whose score_param_id isn't in visible_param_ids (e.g. a
        Custom column made invisible, or deleted, since the group was built)
        is dropped rather than shown as a broken empty row -- pass the
        current visible set to enable this and get back an accurate dropped
        count; leave it None to skip the check (used by tests that only
        care about the reconstruction shape). Returns (groups, dropped_count)."""
        groups_by_id = {}
        order = []
        dropped = 0
        for parameter in selected_parameters:
            group_id = str(parameter.get("group_id") or "")
            if not group_id.startswith(cls.GROUP_ID_PREFIX):
                continue
            kind = str(parameter.get("type") or "categorical").lower()
            if (
                kind != "special"
                and visible_param_ids is not None
                and parameter.get("score_param_id") not in visible_param_ids
            ):
                dropped += 1
                continue
            if group_id not in groups_by_id:
                groups_by_id[group_id] = {
                    "mode": "any"
                    if str(parameter.get("group_mode") or "").lower() == "any"
                    else "all",
                    "conditions": [],
                }
                order.append(group_id)
            if kind == "numeric":
                groups_by_id[group_id]["conditions"].append(
                    {
                        "kind": "numeric",
                        "score_param_id": parameter.get("score_param_id"),
                        "operation": parameter.get("operation"),
                        "value": parameter.get("value"),
                        "value_max": parameter.get("value_max"),
                    }
                )
            elif kind != "special":
                # ids are tagged as "{group_id}:{option_pk}" -- see _tag_grouped_option.
                raw_id = str(parameter.get("id") or "")
                option_id = raw_id.rsplit(":", 1)[-1] if raw_id else None
                score_param_id = parameter.get("score_param_id")
                # Multiple values for the same criterion (e.g. Core + Accessory)
                # render as one condition with several checked values, not one
                # row per value -- matches how the builder UI shows them (a
                # single "OR"-joined row), and how they were submitted.
                existing_condition = next(
                    (
                        condition
                        for condition in groups_by_id[group_id]["conditions"]
                        if condition["kind"] == "categorical"
                        and condition["score_param_id"] == score_param_id
                    ),
                    None,
                )
                if existing_condition is not None:
                    existing_condition["option_ids"].append(option_id)
                else:
                    groups_by_id[group_id]["conditions"].append(
                        {
                            "kind": "categorical",
                            "score_param_id": score_param_id,
                            "option_ids": [option_id],
                        }
                    )
        # A group can end up with zero conditions if every one of them got
        # dropped above (all hidden) -- drop the group itself rather than
        # showing an empty ALL/ANY toggle with nothing under it.
        groups = [
            groups_by_id[group_id] for group_id in order if groups_by_id[group_id]["conditions"]
        ]
        return groups, dropped

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )
        param_options = self._param_options(request.user)
        visible_param_ids = {option["id"] for option in param_options}
        existing_groups, dropped_count = self._existing_groups(
            selected_parameters, visible_param_ids
        )
        if dropped_count:
            messages.warning(
                request,
                f"{dropped_count} condición(es) de un grupo guardado ya no están disponibles "
                "(columna oculta o eliminada) y no se muestran acá.",
            )

        return render(
            request,
            self.template_name,
            {
                "genome": genome,
                "biodb_accession": display_genome_name(assembly_name),
                "assembly_url": reverse(
                    "tpwebapp:assembly", kwargs={"genome": genome_url_slug(assembly_name)}
                ),
                "protein_list_url": reverse("tpwebapp:protein_list", kwargs={"genome": genome}),
                # Raw Python objects, not pre-serialized strings -- the
                # template's |json_script filter does its own json.dumps()
                # (plus HTML-safe escaping), so passing already-dumped JSON
                # here would double-encode it into a string literal.
                "param_options": param_options,
                "existing_groups": existing_groups,
            },
        )

    def post(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )
        # This POST replaces every previously-submitted advanced group wholesale
        # (editing a group changes its numeric filter's id, so a stale copy would
        # otherwise linger) -- the plain panel's own filters are untouched.
        selected_parameters = [
            item
            for item in selected_parameters
            if not str(item.get("group_id") or "").startswith(self.GROUP_ID_PREFIX)
        ]

        try:
            raw_groups = json.loads(request.POST.get("groups_json") or "[]")
        except (TypeError, ValueError):
            raw_groups = []

        changes = []
        applied_group_count = 0
        if isinstance(raw_groups, list):
            for group_index, raw_group in enumerate(raw_groups):
                if not isinstance(raw_group, dict):
                    continue
                conditions = raw_group.get("conditions")
                if not isinstance(conditions, list) or not conditions:
                    continue
                mode = "any" if str(raw_group.get("mode") or "").lower() == "any" else "all"
                group_id = f"{self.GROUP_ID_PREFIX}{group_index}"
                group_had_condition = False
                for raw_condition in conditions:
                    if not isinstance(raw_condition, dict):
                        continue
                    kind = str(raw_condition.get("kind") or "").strip().lower()
                    if kind == "numeric":
                        changes.append(
                            {
                                "action": "add_numeric_filter",
                                "score_param_id": str(raw_condition.get("score_param_id") or ""),
                                "numeric_operation": str(raw_condition.get("operation") or ""),
                                "value": str(raw_condition.get("value") or ""),
                                "value_max": str(raw_condition.get("value_max") or ""),
                                "group_id": group_id,
                                "group_mode": mode,
                            }
                        )
                        group_had_condition = True
                    elif kind == "categorical":
                        # One or more values for the same criterion (e.g. Core +
                        # Accessory) -- each becomes its own add_filter change,
                        # all sharing this group's id/mode. This reuses the
                        # exact mechanism that already makes multiple values of
                        # one categorical param combine as "any of these" (see
                        # selected_parameters_to_filter_map in protein_list.py),
                        # which is the only sensible reading when two different
                        # values of the same single-valued field are both
                        # selected -- true AND between them would never match.
                        option_ids = raw_condition.get("option_ids")
                        if not isinstance(option_ids, list):
                            single = raw_condition.get("option_id")
                            option_ids = [single] if single else []
                        for option_id in option_ids:
                            if not option_id:
                                continue
                            changes.append(
                                {
                                    "action": "add_filter",
                                    "filter_option_id": option_id,
                                    "group_id": group_id,
                                    "group_mode": mode,
                                }
                            )
                            group_had_condition = True
                if group_had_condition:
                    applied_group_count += 1

        selected_parameters = apply_filter_changes(selected_parameters, changes)
        set_workspace_session_value(
            request.session, request.user, "selected_parameters", selected_parameters
        )
        if applied_group_count:
            messages.success(
                request,
                f"{applied_group_count} grupo(s) de filtros avanzados aplicados.",
            )
        elif raw_groups:
            messages.info(request, "No se aplicó ningún grupo de filtros (vacío o inválido).")

        return redirect(reverse("tpwebapp:protein_list", kwargs={"genome": genome}))


class ProteinListView(View):
    template_name = "search/proteins.html"
    VISIBLE_COLUMNS_SESSION_KEY = "protein_visible_columns"
    FIXED_COLUMN_LABELS = (
        "Protein",
        "Description",
        "Gene",
        "Structure",
        "EC",
        "GO",
        "Metabolism",
        "Score",
    )

    @staticmethod
    def _seed_filters_from_link(request, raw_filters_param):
        """Handle a shared-link ?filters= param: decode it, drop anything
        the requesting user can't see (a link can reference a Custom column
        owned by a different user, or since deleted), seed session with
        what's left, then redirect to a clean URL -- ?filters= is a one-time
        seed, not a persistent source of truth (mirrors how preset-apply/
        filter-change POST handlers already redirect after mutating
        session)."""
        decoded = decode_selected_parameters_param(raw_filters_param)
        if decoded is None:
            messages.warning(request, "No pudimos interpretar el link de filtros compartido.")
        else:
            normalized = normalize_selected_parameters(decoded)
            visible_ids = set(
                visible_score_params_queryset(request.user).values_list("pk", flat=True)
            )
            kept, dropped_count = filter_visible_selected_parameters(normalized, visible_ids)
            set_workspace_session_value(request.session, request.user, "selected_parameters", kept)
            if dropped_count:
                messages.warning(
                    request,
                    f"{dropped_count} filtro(s) del link no se pudieron aplicar (columna no disponible para tu usuario).",
                )
        redirect_params = request.GET.copy()
        redirect_params.pop("filters", None)
        redirect_params.pop("page", None)
        redirect_url = request.path
        if redirect_params:
            redirect_url = f"{redirect_url}?{redirect_params.urlencode()}"
        return redirect(redirect_url)

    @staticmethod
    def _clean_redirect_query(
        return_query,
        structure_source="",
        annotation_kind="",
        annotation_value="",
        applied_preset_id=None,
    ):
        params = parse_qs(return_query or "", keep_blank_values=False)
        for key in ("page", "ec_filter", "applied_preset"):
            params.pop(key, None)

        structure_source = (structure_source or "").strip().lower()
        if structure_source:
            params["structure_source"] = [structure_source]
        else:
            params.pop("structure_source", None)

        annotation_value = (annotation_value or "").strip()
        if annotation_value:
            params["annotation_kind"] = [normalize_annotation_kind(annotation_kind or "ec")]
            params["annotation_value"] = [annotation_value]
        else:
            params.pop("annotation_kind", None)
            params.pop("annotation_value", None)

        if applied_preset_id is not None:
            params["applied_preset"] = [str(applied_preset_id)]

        return urlencode(
            {key: value[0] if len(value) == 1 else value for key, value in params.items()},
            doseq=True,
        )

    @staticmethod
    def _apply_filter_change(selected_parameters, change):
        # Thin delegation to the shared, request-agnostic implementation in
        # protein_list.py, which the agent's apply_filters/search_proteins
        # tools also call.
        from tpweb.services.protein_list import apply_filter_change

        return apply_filter_change(selected_parameters, change)

    @classmethod
    def _apply_filter_changes_payload(cls, selected_parameters, payload):
        try:
            changes = json.loads(payload or "[]")
        except (TypeError, ValueError):
            changes = []
        return apply_filter_changes(selected_parameters, changes)

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

    _NUMERIC_FILTER_PLACEHOLDERS = {
        "human_identity": ("30", "80"),
        "micro_identity": ("30", "80"),
        "deg_identity": ("30", "80"),
        "human_evalue": ("1e-5", "0.01"),
        "micro_evalue": ("1e-5", "0.01"),
        "deg_evalue": ("1e-5", "0.01"),
        "colabfold_plddt": ("70", "100"),
        "gut_microbiome_offtarget_counts": ("1", "10"),
        "gut_microbiome_genomes_analyzed": ("100", "200"),
        "gut_microbiome_offtarget_norm": ("0.1", "0.5"),
        "colabfold_druggability_score": ("0.7", "1.0"),
        "colabfold_p2rank_probability": ("0.5", "1.0"),
        "p2rank_probability": ("0.5", "1.0"),
    }

    @staticmethod
    def _build_filter_groups(
        score_params, selected_parameters, structure_choices=None, function_data=None
    ):
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
                ph, ph_max = ProteinListView._NUMERIC_FILTER_PLACEHOLDERS.get(
                    score_param.name, ("0.70", "1.00")
                )
                grouped.setdefault(category, []).append(
                    {
                        "id": score_param.pk,
                        "name": score_param.name,
                        "label": param_label,
                        "description": score_param.description or "",
                        "type": "numeric",
                        "placeholder": ph,
                        "placeholder_max": ph_max,
                        "active_filters": [
                            {
                                "id": entry.get("id"),
                                "display_name": entry.get("display_name", ""),
                            }
                            for entry in active_filters
                        ],
                        "any_active": bool(active_filters),
                        "search_text": (param_label + " " + category).lower(),
                    }
                )
                continue
            param_name_lower = score_param.name.lower()
            if param_name_lower.endswith("_structure") or param_name_lower.endswith("_pocket"):
                continue
            choices = list(score_param.choices.all())
            if not choices:
                continue
            options = []
            search_tokens = [param_label, category]
            any_active = False
            for option in choices:
                if param_name_lower.endswith("_pocket"):
                    raw = (option.name or "").strip()
                    if raw == "No_pockets":
                        option_label = "No pockets"
                    elif raw.lower().startswith("pocket pocket"):
                        suffix = raw[len("pocket pocket") :].strip()
                        option_label = f"Pocket {suffix}" if suffix else "Pocket"
                    else:
                        option_label = raw or option.name
                else:
                    option_label = humanize_identifier(option.name) or option.name
                option_active = str(option.pk) in selected_option_ids
                if option_active:
                    any_active = True
                option_tone = ""
                normalized_option_name = str(option.name or "").strip().lower()
                if score_param.name in {"human_offtarget", "gut_microbiome_offtarget"}:
                    if normalized_option_name in {"hit", "y", "yes"}:
                        option_tone = "risk"
                    elif normalized_option_name in {"no_hit", "no hit", "n", "no"}:
                        option_tone = "favorable"
                elif param_name_lower in {"core_roary", "core_corecruncher"}:
                    if option.name == "Core":
                        option_tone = "favorable"
                    elif option.name == "Accessory":
                        option_tone = "secondary"
                elif param_name_lower == "hit_in_deg":
                    if normalized_option_name == "y":
                        option_tone = "favorable"
                    elif normalized_option_name == "n":
                        option_tone = "secondary"
                elif param_name_lower == "localization":
                    if normalized_option_name in {
                        "extracellular",
                        "outermembrane",
                        "outer membrane",
                        "cellwall",
                        "periplasmic",
                        "cytoplasmicmembrane",
                        "cytoplasmic membrane",
                    }:
                        option_tone = "favorable"
                    elif normalized_option_name == "cytoplasmic":
                        option_tone = "risk"
                options.append(
                    {
                        "id": option.pk,
                        "name": option.name,
                        "label": option_label,
                        "description": option.description or "",
                        "active": option_active,
                        "tone": option_tone,
                    }
                )
                search_tokens.append(option_label)
            grouped.setdefault(category, []).append(
                {
                    "id": score_param.pk,
                    "name": score_param.name,
                    "label": param_label,
                    "description": score_param.description or "",
                    "type": "categorical",
                    "options": options,
                    "any_active": any_active,
                    "search_text": " ".join(search_tokens).lower(),
                }
            )

        preferred_order = [
            "Pocket",
            "Off-target",
            "Essentiality",
            "Conservation",
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
            filter_groups.append(
                {
                    "category": "Function",
                    "is_function": True,
                    "ec_classes": ec_classes,
                    "ec_specific_active": ec_specific_active,
                    "go_active": go_active,
                    "ec_explorer_url": ec_explorer_url,
                    "any_active": any_function_active,
                    "param_count": len(ec_specific_active)
                    + len(go_active)
                    + sum(1 for c in ec_classes if c.get("active")),
                }
            )

        structure_choices = [choice for choice in (structure_choices or []) if choice.get("value")]
        if structure_choices:
            active_structure = next(
                (choice for choice in structure_choices if choice.get("active")), None
            )
            filter_groups.append(
                {
                    "category": "Structure",
                    "params": [
                        {
                            "id": "structure_source",
                            "name": "structure_source",
                            "label": "3D evidence source",
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
                            "search_text": "3d evidence structure source "
                            + " ".join(choice["label"] for choice in structure_choices).lower(),
                        }
                    ],
                    "any_active": bool(active_structure),
                    "param_count": 1 if active_structure else 0,
                }
            )

        active_ligand_value = (function_data or {}).get("ligand_active")
        filter_groups.append(
            {
                "category": "Ligands",
                "is_ligand_filter": True,
                "ligand_options": [
                    {
                        "value": choice_value,
                        "label": choice_label,
                        "active": bool(active_ligand_value)
                        and active_ligand_value.get("value") == choice_value,
                        "id": (
                            active_ligand_value.get("id")
                            if active_ligand_value
                            and active_ligand_value.get("value") == choice_value
                            else None
                        ),
                    }
                    for choice_value, choice_label in (
                        ("yes", "Has ligand evidence"),
                        ("no", "No ligand evidence"),
                    )
                ],
                "any_active": bool(active_ligand_value),
                "param_count": 1 if active_ligand_value else 0,
            }
        )

        for category in sorted(grouped.keys(), key=_category_sort_key):
            params = sorted(grouped[category], key=lambda entry: _param_sort_key(category, entry))
            any_active = any(entry["any_active"] for entry in params)
            filter_groups.append(
                {
                    "category": category,
                    "params": params,
                    "any_active": any_active,
                    "param_count": sum(1 for entry in params if entry.get("any_active")),
                }
            )
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
            {"value": "alphafold", "label": "AlphaFold DB model"},
            {"value": "colabfold", "label": "ColabFold model"},
            {"value": "none", "label": "No structure"},
        ]
        choices = []
        for choice in base_choices:
            params = request.GET.copy()
            params["pageSize"] = page_size
            params["structure_source"] = choice["value"]
            if "page" in params:
                params.pop("page")
            choices.append(
                {
                    **choice,
                    "active": current_value == choice["value"],
                    "url": f"?{params.urlencode()}",
                }
            )
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
    def _build_table_rows(
        assembly_name,
        protein_ids,
        needed_score_param_names,
        col_descriptions,
        coefficient_by_param,
        expression=None,
        zero_cache=None,
    ):
        if not protein_ids:
            return [], {}

        spv_qs = ScoreParamValue.objects.select_related("score_param")
        if needed_score_param_names is not None:
            spv_qs = spv_qs.filter(score_param__name__in=needed_score_param_names)

        proteins_queryset = (
            Bioentry.objects.filter(
                biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
                bioentry_id__in=protein_ids,
            )
            .annotate(
                metabolic_reaction_count=Count("metabolic_reactions", distinct=True),
                metabolic_chokepoint_count=Count(
                    "metabolic_reactions",
                    filter=~Q(metabolic_reactions__chokepoint_role="none"),
                    distinct=True,
                ),
            )
            .prefetch_related(
                "qualifiers__term",
                "structures__pdb",
                "dbxrefs__dbxref__terms__term",
                Prefetch("score_params", queryset=spv_qs),
            )
        )

        proteins_map = {protein.bioentry_id: protein for protein in proteins_queryset}
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
        for score_param, values in grouped_parameters:
            filters_text.append(f"{score_param}: {values}")

        if structure_source:
            filters_text.append(f"Structure filter: {humanize_identifier(structure_source)}")

        if annotation_filter:
            label = (
                annotation_filter.get("kind_label") or annotation_filter.get("kind") or "Annotation"
            )
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

        data_headers = [
            "Rank",
            "Protein",
            "Description",
            "Gene",
            "Structure",
            "EC",
            "GO",
            "Metabolism",
        ] + list(tcolumns)

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
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        workspace_user = resolve_workspace_user(request.user)
        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )

        action = request.POST.get("action")
        applied_preset_id = None
        current_structure_source = request.GET.get("structure_source", "").strip().lower()
        target_structure_source = current_structure_source
        target_annotation_kind = normalize_annotation_kind(request.GET.get("annotation_kind", "ec"))
        target_annotation_value = request.GET.get("annotation_value", "").strip()
        if request.GET.get("ec_filter", "").strip():
            target_annotation_kind = "ec"
            target_annotation_value = request.GET.get("ec_filter", "").strip()

        if action == "add_filter":
            selected_parameters = self._apply_filter_change(
                selected_parameters,
                {"action": action, "filter_option_id": request.POST.get("filter_option_id")},
            )

        elif action == "add_special_filter":
            selected_parameters = self._apply_filter_change(
                selected_parameters,
                {
                    "action": action,
                    "special_kind": request.POST.get("special_kind"),
                    "special_value": request.POST.get("special_value"),
                },
            )

        elif action == "add_numeric_filter":
            selected_parameters = self._apply_filter_change(
                selected_parameters,
                {
                    "action": action,
                    "score_param_id": request.POST.get("score_param_id"),
                    "numeric_operation": request.POST.get("numeric_operation"),
                    "value": request.POST.get("value"),
                    "value_max": request.POST.get("value_max"),
                },
            )

        elif action == "remove_filter":
            selected_parameters = self._apply_filter_change(
                selected_parameters,
                {"action": action, "filter_option_id": request.POST.get("filter_option_id")},
            )

        elif action == "set_structure_filter":
            requested_structure = (request.POST.get("structure_source") or "").strip().lower()
            target_structure_source = (
                "" if requested_structure == current_structure_source else requested_structure
            )

        elif action == "apply_filter_changes":
            selected_parameters = self._apply_filter_changes_payload(
                selected_parameters,
                request.POST.get("filter_actions_json"),
            )
            target_structure_source = (
                (request.POST.get("pending_structure_source") or "").strip().lower()
            )
            target_annotation_kind = normalize_annotation_kind(
                request.POST.get("pending_annotation_kind") or target_annotation_kind
            )
            target_annotation_value = (request.POST.get("pending_annotation_value") or "").strip()

        elif action == "save_filter_preset":
            selected_parameters = self._apply_filter_changes_payload(
                selected_parameters,
                request.POST.get("filter_actions_json"),
            )
            target_structure_source = (
                (request.POST.get("pending_structure_source") or "").strip().lower()
            )
            target_annotation_kind = normalize_annotation_kind(
                request.POST.get("pending_annotation_kind") or target_annotation_kind
            )
            target_annotation_value = (request.POST.get("pending_annotation_value") or "").strip()
            preset_name = (request.POST.get("preset_name") or "").strip()
            if preset_name:
                saved_preset, _ = FilterPreset.objects.update_or_create(
                    owner=workspace_user,
                    genome_name=assembly_name,
                    name=preset_name,
                    defaults={
                        "selected_parameters": normalize_selected_parameters(selected_parameters),
                        "structure_source": target_structure_source,
                        "annotation_kind": target_annotation_kind
                        if target_annotation_value
                        else "",
                        "annotation_value": target_annotation_value,
                    },
                )
                applied_preset_id = saved_preset.pk

        elif action == "apply_filter_preset":
            preset_id = request.POST.get("preset_id")
            preset = FilterPreset.objects.filter(
                id=preset_id,
                owner=workspace_user,
                genome_name=assembly_name,
            ).first()
            if preset:
                selected_parameters = normalize_selected_parameters(preset.selected_parameters)
                target_structure_source = preset.structure_source or ""
                target_annotation_kind = normalize_annotation_kind(preset.annotation_kind or "ec")
                target_annotation_value = preset.annotation_value or ""
                applied_preset_id = preset.pk

        elif action == "delete_filter_preset":
            preset_id = request.POST.get("preset_id")
            FilterPreset.objects.filter(
                id=preset_id,
                owner=workspace_user,
                genome_name=assembly_name,
            ).delete()

        elif action == "reset_filters":
            selected_parameters = []
            target_structure_source = ""
            target_annotation_value = ""

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
        redirect_query = self._clean_redirect_query(
            return_query,
            structure_source=target_structure_source,
            annotation_kind=target_annotation_kind,
            annotation_value=target_annotation_value,
            applied_preset_id=applied_preset_id,
        )
        redirect_url = request.path
        if redirect_query:
            redirect_url = f"{redirect_url}?{redirect_query}"
        return redirect(redirect_url)

    def _resolve_visible_columns(
        self, request, formula, formula_term_list, visible_score_param_by_name, col_descriptions
    ):
        default_column_names = [
            score_param.name for score_param in ordered_score_params(formula_term_list)
        ]
        if not default_column_names:
            # No formula active -- default to Druggability + p2rank_probability columns
            # if they exist. p2rank_probability listed first: the default ranking below
            # (_drugg_default) sorts by it when present, falling back to Druggability's
            # FPocket score only for proteins with no P2Rank value -- showing both
            # columns, in that order, is what actually explains the resulting row order
            # instead of the FPocket column alone looking unsorted.
            default_column_names = [
                name
                for name in [
                    "p2rank_probability",
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
            score_param.name: (score_param.description or "") for score_param in ordered_params
        }
        if "Score" in tcolumns:
            selected_col_descriptions["Score"] = (
                "Weighted prioritization score from the selected formula."
            )
        col_descriptions = {
            **selected_col_descriptions,
            **col_descriptions,
        }

        if formula is None:
            tcolumns = [c for c in tcolumns if c != "Score"]

        return default_column_names, selected_column_names, score_dict, tcolumns, col_descriptions

    @staticmethod
    def _rank_and_sort_proteins(
        ranking_queryset,
        formula_expression,
        zero_cache,
        coefficient_by_param,
        _drugg_default,
        sort_by_param,
        sort_by_score,
        effective_sort_col,
        effective_sort_dir,
        selected_parameters,
        needed_score_param_names,
    ):
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
                if _drugg_default:
                    p2rank_value = param_values.get("p2rank_probability")
                    col_val = (
                        p2rank_value
                        if p2rank_value is not None
                        else param_values.get("Druggability")
                    )
                elif sort_by_param:
                    col_val = param_values.get(sort_by_param)
                else:
                    col_val = None
                ranked_proteins.append(
                    {
                        "id": protein.bioentry_id,
                        "accession": protein.accession,
                        "score": score_value,
                        "col_val": col_val,
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
            return non_null + null_group
        if sort_by_score:
            if effective_sort_dir == "asc":
                return sorted(ranked_proteins, key=lambda p: (p["score"], p["accession"]))
            return sorted(ranked_proteins, key=lambda p: (-p["score"], p["accession"]))
        return sorted(
            ranked_proteins,
            key=lambda p: p["accession"],
            reverse=(effective_sort_dir == "desc"),
        )

    @staticmethod
    def _apply_structure_and_annotation_filters(
        assembly_name, structure_source, annotation_kind, annotation_value
    ):
        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
        )
        total_protein_count = proteins.count()
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

        return proteins, total_protein_count

    @staticmethod
    def _build_filter_presets(workspace_user, assembly_name, last_applied_preset_id):
        filter_presets = []
        for preset in FilterPreset.objects.filter(
            owner=workspace_user,
            genome_name=assembly_name,
        ).order_by("name", "id"):
            selected = normalize_selected_parameters(preset.selected_parameters)
            criteria_labels = []
            grouped_categorical = {}
            for item in selected:
                item_kind = str(item.get("type") or "categorical").strip().lower()
                param_name_raw = item.get("score_param_name") or ""
                if item_kind in ("", "categorical") and param_name_raw:
                    human_val = humanize_identifier(item.get("name", ""))
                    grouped_categorical.setdefault(humanize_identifier(param_name_raw), []).append(
                        human_val
                    )
                elif item_kind == "numeric" and param_name_raw:
                    human_name = humanize_identifier(param_name_raw)
                    op = item.get("operation", "")
                    val = item.get("value")
                    val_max = item.get("value_max")
                    if op == "between" and val is not None and val_max is not None:
                        criteria_labels.append(f"{human_name}: {val:g}–{val_max:g}")
                    elif val is not None:
                        criteria_labels.append(f"{human_name} {op} {val:g}")
                elif item_kind == "special":
                    display_name = item.get("display_name") or item.get("name", "")
                    special_key = str(item.get("special_key") or "").strip()
                    if display_name:
                        if special_key == "ec_filter":
                            criteria_labels.append(f"EC class: {humanize_identifier(display_name)}")
                        elif special_key == "go_filter":
                            criteria_labels.append(f"GO: {display_name}")
                        elif special_key == "structure_source":
                            criteria_labels.append(
                                f"Structure: {humanize_identifier(display_name)}"
                            )
                        else:
                            criteria_labels.append(humanize_identifier(display_name))
            for param_label, values in grouped_categorical.items():
                criteria_labels.append(f"{param_label}: {', '.join(values)}")
            if preset.structure_source:
                criteria_labels.append(f"Structure: {humanize_identifier(preset.structure_source)}")
            if preset.annotation_value:
                ann_kind = normalize_annotation_kind(preset.annotation_kind or "ec")
                ann_label = annotation_kind_label(ann_kind) if ann_kind else "Annotation"
                criteria_labels.append(f"{ann_label}: {preset.annotation_value}")
            filter_presets.append(
                {
                    "id": preset.pk,
                    "name": preset.name,
                    "criteria_count": (
                        len(selected)
                        + (1 if preset.structure_source else 0)
                        + (1 if preset.annotation_value else 0)
                    ),
                    "criteria_labels": criteria_labels[:8],
                    "is_last_applied": preset.pk == last_applied_preset_id,
                }
            )
        return filter_presets

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        raw_filters_param = request.GET.get("filters")
        if raw_filters_param is not None:
            return self._seed_filters_from_link(request, raw_filters_param)

        page_size = parse_page_size(request.GET.get("pageSize", DEFAULT_PAGE_SIZE))
        clear_search_url = self._build_clear_search_url(request, page_size)
        formulas = resolve_formulas_for_user(request.user)
        requested_formula = request.GET.get("scoreformula", NO_FORMULA_SENTINEL)
        formula = choose_formula(formulas, requested_formula)

        bdb = Biodatabase.objects.get(name=assembly_name)

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
        all_term_descriptions = build_all_term_descriptions()
        formulas_for_drawer = []
        for f in formulas:
            formula_expression = f.get_current_formula()
            formulas_for_drawer.append(
                {
                    "pk": f.pk,
                    "name": f.name,
                    "is_default": bool(f.default),
                    "is_current": f.pk == current_formula_pk,
                    "expression": formula_expression,
                    "term_help": annotate_formula_terms(formula_expression, all_term_descriptions),
                    "is_user_formula": f.user_id is not None
                    and f.user_id == getattr(workspace_user_for_drawer, "pk", None),
                }
            )

        workspace_user = resolve_workspace_user(request.user)
        custom_data_files = list(
            CustomParam.objects.filter(owner=workspace_user, accession=assembly_name).order_by(
                "tsv"
            )
        )
        custom_data_for_drawer = [{"file_name": Path(cp.tsv.name).name} for cp in custom_data_files]
        last_applied_preset_raw = request.GET.get("applied_preset", "")
        try:
            last_applied_preset_id = int(last_applied_preset_raw)
        except (TypeError, ValueError):
            last_applied_preset_id = None

        filter_presets = self._build_filter_presets(
            workspace_user, assembly_name, last_applied_preset_id
        )
        active_preset_name = next((p["name"] for p in filter_presets if p["is_last_applied"]), "")

        all_visible_score_params = list(
            visible_score_params_queryset(request.user).prefetch_related("choices")
        )
        visible_score_param_by_name = {
            score_param.name: score_param for score_param in all_visible_score_params
        }
        default_column_names, selected_column_names, score_dict, tcolumns, col_descriptions = (
            self._resolve_visible_columns(
                request, formula, formula_term_list, visible_score_param_by_name, col_descriptions
            )
        )

        tdatas = {}
        page = request.GET.get("page", 1)
        search_query = request.GET.get("search", "").strip()
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
        proteins, total_protein_count = self._apply_structure_and_annotation_filters(
            assembly_name, structure_source, annotation_kind, annotation_value
        )

        selected_parameters = normalize_selected_parameters(
            get_workspace_session_value(request.session, request.user, "selected_parameters", [])
        )
        grouped_parameters = grouped_selected_parameters(selected_parameters, humanize=True)

        def _display_filter_option_name(parameter):
            if str(parameter.get("type") or "").lower() in {"numeric", "special"}:
                return parameter.get("display_name")
            raw_name = parameter.get("name") or ""
            param_name = str(parameter.get("score_param_name") or "").lower()
            if param_name.endswith("_structure"):
                return raw_name
            if param_name.endswith("_pocket"):
                if raw_name == "No_pockets":
                    return "No pockets"
                if raw_name.lower().startswith("pocket pocket"):
                    suffix = raw_name[len("pocket pocket") :].strip()
                    return f"Pocket {suffix}" if suffix else "Pocket"
                return raw_name
            return humanize_identifier(raw_name) or raw_name

        display_parameters = [
            {
                **parameter,
                "display_score_param_name": (
                    humanize_identifier(parameter.get("score_param_name"))
                    or parameter.get("score_param_name")
                ),
                "name": parameter.get("name") or parameter.get("display_name") or "",
                "display_name": _display_filter_option_name(parameter),
            }
            for parameter in selected_parameters
        ]

        if selected_parameters:
            try:
                proteins = apply_selected_parameter_filters(proteins, selected_parameters)
            except Exception:
                logger.exception(
                    "Failed to build protein selected-parameter filters: %s", selected_parameters
                )
                raise

        proteins = apply_protein_search(proteins, search_query)

        formula_expression = getattr(formula, "expression", "") or ""
        formula_param_names = {term.score_param.name for term in formula_term_list}
        column_param_names = set(selected_column_names)
        # Include sort column in prefetch when it's a score param column
        sort_param_for_prefetch = raw_sort_col if raw_sort_col in selected_column_names else None
        # When no formula and no explicit sort, default to Druggability desc if available --
        # preferring P2Rank's value over FPocket's own per protein (roadmap: P2Rank is the
        # primary druggability signal shown everywhere else in the app -- protein page,
        # metabolism ranking, workspace counts), falling back to FPocket when a protein has
        # no P2Rank value loaded. An explicit sort_col=Druggability click (the column header)
        # still sorts by the raw FPocket score only -- this only changes the untouched,
        # land-on-the-page default. The "Druggability" column's own displayed values, its
        # ScoreFormula term, and CSV export are unaffected: this only substitutes the sort key.
        _drugg_default = (
            not raw_sort_col and formula is None and "Druggability" in selected_column_names
        )
        if formula_expression:
            zero_cache = build_all_options_zero(request.user)
            needed_score_param_names = None  # prefetch all for expression scoring
        else:
            zero_cache = None
            needed_score_param_names = formula_param_names | column_param_names
            if sort_param_for_prefetch:
                needed_score_param_names = needed_score_param_names | {sort_param_for_prefetch}
            if _drugg_default:
                needed_score_param_names = needed_score_param_names | {
                    "Druggability",
                    "p2rank_probability",
                }

        ranking_spv_qs = ScoreParamValue.objects.select_related("score_param")
        if needed_score_param_names is not None:
            ranking_spv_qs = ranking_spv_qs.filter(score_param__name__in=needed_score_param_names)

        ranking_queryset = (
            proteins.only(
                "bioentry_id",
                "accession",
                "name",
                "description",
            )
            .prefetch_related(Prefetch("score_params", queryset=ranking_spv_qs))
            .distinct()
        )

        coefficient_by_param = coefficient_map(formula_term_list)

        # Resolve effective sort: which column and direction
        sort_by_param = (
            raw_sort_col
            if raw_sort_col in selected_column_names
            else ("Druggability" if _drugg_default else None)
        )
        sort_by_score = (raw_sort_col == "Score" and formula is not None) or (
            not raw_sort_col and formula is not None and not sort_by_param
        )
        sort_by_accession = not sort_by_param and not sort_by_score
        effective_sort_col = sort_by_param or ("Score" if sort_by_score else "__accession__")
        effective_sort_dir = raw_sort_dir or ("asc" if sort_by_accession else "desc")

        ranked_proteins = self._rank_and_sort_proteins(
            ranking_queryset,
            formula_expression,
            zero_cache,
            coefficient_by_param,
            _drugg_default,
            sort_by_param,
            sort_by_score,
            effective_sort_col,
            effective_sort_dir,
            selected_parameters,
            needed_score_param_names,
        )

        filtered_protein_count = len(ranked_proteins)

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
            headers = [
                "Rank",
                "Protein",
                "Description",
                "Gene",
                "Structure",
                "EC",
                "GO",
                "Metabolism",
            ] + tcolumns
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
                        protein.get("metabolism_text") or "-",
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
                    }
                    if annotation_value
                    else None,
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

        share_params = query_params.copy()
        if selected_parameters:
            share_params["filters"] = encode_selected_parameters(selected_parameters)
        share_url = request.build_absolute_uri(f"{request.path}?{share_params.urlencode()}")

        structure_source_choices = self._build_structure_source_choices(
            request, page_size, structure_source
        )

        active_ec_values = []
        active_go_values = []
        active_ligand_value = None
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
            elif special_key == "ligand_filter" and special_value:
                active_ligand_value = {"value": special_value, "id": entry_id}

        ec_class_value_set = {value for value, _ in self.EC_CLASSES}
        active_ec_class_set = {
            entry["value"] for entry in active_ec_values if entry["value"] in ec_class_value_set
        }
        ec_specific_active = [
            entry for entry in active_ec_values if entry["value"] not in ec_class_value_set
        ]

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
            "ligand_active": active_ligand_value,
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
            "proteins": proteins_page,
            "has_previous": proteins_page.has_previous(),
            "has_next": proteins_page.has_next(),
            "previous_page_number": proteins_page.previous_page_number()
            if proteins_page.has_previous()
            else None,
            "next_page_number": proteins_page.next_page_number()
            if proteins_page.has_next()
            else None,
            "number": proteins_page.number,
            "num_pages": proteins_page.paginator.num_pages,
            "page_range": proteins_page.paginator.page_range,
        }
        page_numbers = self._build_page_numbers(
            proteins_page.number, proteins_page.paginator.num_pages
        )
        pipeline_status = annotate_pipeline_status_for_genome(get_pipeline_status(), bdb.name)
        annotation_filter = (
            {
                "kind": annotation_kind,
                "kind_label": annotation_kind_label(annotation_kind),
                "value": annotation_value,
                "name": annotation_term_name(annotation_kind, annotation_value),
            }
            if annotation_value
            else None
        )
        structure_filter = next(
            (choice for choice in structure_source_choices if choice.get("active")),
            None,
        )

        sort_col_urls = {
            "__accession__": self._build_sort_url(
                request, "__accession__", effective_sort_col, effective_sort_dir, default_dir="asc"
            ),
        }
        if formula is not None:
            sort_col_urls["Score"] = self._build_sort_url(
                request, "Score", effective_sort_col, effective_sort_dir, default_dir="desc"
            )
        for _col in tcolumns:
            if _col == "Score":
                continue
            sort_col_urls[_col] = self._build_sort_url(
                request, _col, effective_sort_col, effective_sort_dir, default_dir="desc"
            )

        sort_label_by_col = {"__accession__": "Protein"}
        sort_label_by_col.update({col: humanize_identifier(col) or col for col in tcolumns})
        if _drugg_default:
            # The default (no explicit sort_col) case sorts by a P2Rank-preferred value,
            # not the raw FPocket score humanize_identifier's "Druggability (FPocket)"
            # label would otherwise imply -- an explicit column-header click still says
            # "(FPocket)" correctly, since that path sorts by the raw column only.
            sort_label_by_col["Druggability"] = "Druggability (P2Rank preferred)"
        sort_direction_label = "ascending" if effective_sort_dir == "asc" else "descending"
        sorted_by_label = f"{sort_label_by_col.get(effective_sort_col, effective_sort_col)} ({sort_direction_label})"

        is_default_view = not (
            formula
            or grouped_parameters
            or structure_source
            or annotation_filter
            or active_preset_name
            or search_query
            or raw_sort_col
            or raw_sort_dir
            or page_size != DEFAULT_PAGE_SIZE
        )

        return render(
            request,
            self.template_name,
            {
                "biodb__name": bdb.description if bdb.description else bdb.name,
                "biodb_accession": display_genome_name(bdb.name),
                "biodb_description": bdb.description if bdb.description else "",
                "assembly_url": reverse(
                    "tpwebapp:assembly", kwargs={"genome": genome_url_slug(assembly_name)}
                ),
                "advanced_filters_url": reverse(
                    "tpwebapp:protein_advanced_filters", kwargs={"genome": genome}
                ),
                "proteins": proteins_dto,
                "score_dict": score_dict,
                "tcolumns": tcolumns,
                "tdata": page_tdatas,
                "formula": formuladto,
                "col_descriptions": col_descriptions,
                "formulas": formulas,
                "formulas_for_drawer": formulas_for_drawer,
                "custom_data_for_drawer": custom_data_for_drawer,
                "custom_data_count": len(custom_data_for_drawer),
                "filter_presets": filter_presets,
                "active_preset_name": active_preset_name,
                "custom_score_url": reverse(
                    "tpwebapp:formula_form", kwargs={"genome": genome_url_slug(assembly_name)}
                ),
                "custom_data_url": reverse(
                    "tpwebapp:customparam", kwargs={"genome": genome_url_slug(assembly_name)}
                ),
                "current_formula": current_formula,
                "formula_term_count": len(formula_term_list),
                "query_string": query_string,
                "share_url": share_url,
                "genome": genome_url_slug(assembly_name),
                "assembly_name": assembly_name,
                "assembly_label": display_genome_name(assembly_name),
                "parameters": selected_parameters,
                "selection_criteria_count": (
                    len(selected_parameters)
                    + (1 if annotation_value else 0)
                    + (1 if structure_filter else 0)
                ),
                "display_parameters": display_parameters,
                "grouped_parameters": grouped_parameters,
                "pagination": pagination_info,
                "page_size": page_size,
                "search_query": search_query,
                "filtered_protein_count": filtered_protein_count,
                "total_protein_count": total_protein_count,
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
                "column_rows": self._build_column_rows(
                    all_visible_score_params, selected_column_names
                ),
                "selected_column_names": selected_column_names,
                "selected_column_count": len(selected_column_names),
                "default_column_names": default_column_names,
                "fixed_column_labels": [
                    label
                    for label in self.FIXED_COLUMN_LABELS
                    if label != "Score" or formula is not None
                ],
                "export_url": build_export_url(request, strip_params=("page",)),
                "view_export_url": build_view_export_url(request, strip_params=("page",)),
                "sort_col": effective_sort_col,
                "sort_dir": effective_sort_dir,
                "sort_col_urls": sort_col_urls,
                "sorted_by_label": sorted_by_label,
                "formula_active": formula is not None,
                "is_default_view": is_default_view,
            },
        )

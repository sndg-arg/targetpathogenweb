from django.views import View
from django.shortcuts import render
from django.db.models import Prefetch
from django.http import JsonResponse
from urllib.parse import urlencode
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q

from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.ScoreParam import ScoreParamOptions
from django.shortcuts import redirect
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
    build_col_descriptions,
    build_score_dict_and_columns,
    choose_formula,
    coefficient_map,
    formula_to_dto,
    ordered_score_params,
    resolve_formulas_for_user,
)
from tpweb.services.protein_serializer import build_protein_table_row
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
)


class ProteinSearchSuggestionsView(View):
    def get(self, request, assembly_name, *args, **kwargs):
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

    @staticmethod
    def _build_clear_search_url(request, page_size):
        params = {"pageSize": page_size}
        scoreformula = request.GET.get("scoreformula")
        if scoreformula:
            params["scoreformula"] = scoreformula
        return f"?{urlencode(params)}"

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

    def post(self, request, assembly_name, *args, **kwargs):
        selected_parameters = normalize_selected_parameters(
            request.session.get("selected_parameters", [])
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

        elif action == "remove_filter":
            option_id = request.POST.get("filter_option_id")
            if option_id:
                selected_parameters = remove_selected_parameter(
                    selected_parameters, option_id
                )

        elif action == "reset_filters":
            selected_parameters = []

        request.session['selected_parameters'] = selected_parameters

        return_query = request.POST.get("return_query", "").strip()
        redirect_url = request.path
        if return_query:
            redirect_url = f"{redirect_url}?{return_query}"
        return redirect(redirect_url)

    def get(self, request, assembly_name, *args, **kwargs):
        page_size = parse_page_size(request.GET.get("pageSize", DEFAULT_PAGE_SIZE))
        clear_search_url = self._build_clear_search_url(request, page_size)
        formulas = resolve_formulas_for_user(request.user)
        formula = choose_formula(formulas, request.GET.get("scoreformula"))

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

        ordered_params = ordered_score_params(formula_term_list)
        score_dict, tcolumns = build_score_dict_and_columns(ordered_params)

        tdatas = {}
        page = request.GET.get('page', 1)
        search_query = request.GET.get('search', '').strip()
        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            #structures__isnull=False
        )

        selected_parameters = normalize_selected_parameters(
            request.session.get("selected_parameters", [])
        )
        grouped_parameters = grouped_selected_parameters(selected_parameters, humanize=True)
        display_parameters = [
            {
                **parameter,
                "display_score_param_name": (
                    humanize_identifier(parameter.get("score_param_name")) or parameter.get("score_param_name")
                ),
                "display_name": (
                    humanize_identifier(parameter.get("name")) or parameter.get("name")
                ),
            }
            for parameter in selected_parameters
        ]

        if selected_parameters:
            proteins = apply_selected_parameter_filters(proteins, selected_parameters)

        proteins = apply_protein_search(proteins, search_query)

        formula_param_names = {term.score_param.name for term in formula_term_list}
        proteins = proteins.prefetch_related(
            "qualifiers__term",
            Prefetch(
                "score_params",
                queryset=ScoreParamValue.objects.filter(
                    score_param__name__in=formula_param_names
                ).select_related("score_param")
            )
        ).distinct()

        coefficient_by_param = coefficient_map(formula_term_list)

        proteins_dto = []
        for protein in proteins:
            protein_dto, tdata, _ = build_protein_table_row(
                protein,
                visible_columns=col_descriptions,
                coefficient_by_param=coefficient_by_param,
            )
            tdatas[protein.bioentry_id] = tdata

            proteins_dto.append(protein_dto)
        proteins_dto = sorted(proteins_dto, key=lambda x: (-x["score"], x["accession"]))

        paginator = Paginator(proteins_dto, page_size)
        try:
            proteins_page = paginator.page(page)
        except PageNotAnInteger:
            proteins_page = paginator.page(1)
        except EmptyPage:
            proteins_page = paginator.page(paginator.num_pages)

        proteins_ids_paginated = [protein["id"] for protein in proteins_page.object_list]
        page_tdatas = {pid: tdatas.get(pid, {}) for pid in proteins_ids_paginated}

        query_params = request.GET.copy()
        if "page" in query_params:
            query_params.pop("page")
        query_string = query_params.urlencode()

        if formula_term_list:
            filter_options = ScoreParamOptions.objects.filter(
                score_param_id__in=[term.score_param_id for term in formula_term_list]
            ).select_related("score_param").order_by("score_param__name", "name")
        else:
            filter_options = ScoreParamOptions.objects.none()

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

        return render(request, self.template_name, {
            "biodb__name": bdb.description if bdb.description else bdb.name,
            "biodb_accession": bdb.name,
            "biodb_description": bdb.description if bdb.description else "",
            "proteins": proteins_page.object_list,
            "score_dict": score_dict,
            "tcolumns": tcolumns,
            "tdata": page_tdatas,
            "formula": formuladto,
            "col_descriptions": col_descriptions,
            "formulas":formulas,
            "current_formula":current_formula,
            "formula_term_count": len(formula_term_list),
            "query_string": query_string,
            "assembly_name":assembly_name,
            "parameters":selected_parameters,
            "display_parameters":display_parameters,
            "grouped_parameters":grouped_parameters,
            "pagination":pagination_info,
            "page_size": page_size,
            "search_query": search_query,
            "page_numbers": page_numbers,
            "filter_options": filter_options,
            "pipeline_status": pipeline_status,
            "clear_search_url": clear_search_url,

        })  # , {'form': form})

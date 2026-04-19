from django.shortcuts import render, redirect
from django.http import Http404
from django.urls import reverse
from tpweb.views.ParameterForm import (
    ParameterForm,
    SPECIAL_PARAM_EC_NUMBER,
    SPECIAL_PARAM_GO_TERM,
    SPECIAL_PARAM_STRUCTURE,
    humanize_identifier,
)
from tpweb.services.score_param_types import score_param_kind
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, resolve_genome_from_slug
from tpweb.services.score_params import visible_score_param_options_queryset, visible_score_params_queryset
from tpweb.services.protein_annotations import normalize_annotation_kind
from tpweb.services.workspace import (
    get_workspace_session_value,
    pop_workspace_session_value,
    set_workspace_session_value,
)
from tpweb.services.csv_exports import xlsx_sections_response


def ParameterFormView(request, genome):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")
    selected_parameters = get_workspace_session_value(
        request.session, request.user, "selected_parameters", []
    )
    parameterform = ParameterForm(request.POST or None, user=request.user)
    duplicate_filter = False
    structure_source = request.GET.get("structure_source", "").strip().lower()
    annotation_kind = normalize_annotation_kind(request.GET.get("annotation_kind", "ec"))
    annotation_value = request.GET.get("annotation_value", "").strip()
    ec_filter_value = request.GET.get("ec_filter", "").strip()
    if not ec_filter_value and annotation_kind == "ec":
        ec_filter_value = annotation_value
    structure_source_choices = [
        {"value": "", "label": "All"},
        {"value": "experimental", "label": "Experimental"},
        {"value": "alphafold", "label": "AlphaFold"},
        {"value": "colabfold", "label": "ColabFold"},
        {"value": "none", "label": "No structure"},
    ]

    def redirect_with_query(route_name):
        url = redirect(route_name, genome=genome_url_slug(assembly_name))
        params = request.GET.copy()
        query = params.urlencode()
        if query:
            url["Location"] = f"{url['Location']}?{query}"
        return url

    def build_numeric_filter_payload(form):
        score_param = form.cleaned_data["resolved_param"]
        operation = form.cleaned_data["numeric_operation"]
        value = form.cleaned_data["numeric_value"]
        value_max = form.cleaned_data.get("numeric_value_max")
        display_value = f"{operation} {value:g}"
        filter_id = f"numeric:{score_param.id}:{operation}:{value:g}"
        if operation == "between" and value_max is not None:
            display_value = f"{operation} {value:g} - {value_max:g}"
            filter_id = f"{filter_id}:{value_max:g}"
        return {
            "id": filter_id,
            "score_param_id": score_param.id,
            "score_param_name": score_param.name,
            "type": "numeric",
            "operation": operation,
            "value": value,
            "value_max": value_max,
            "display_name": display_value,
        }

    def build_special_filter_payload(form):
        param_value = form.cleaned_data.get("param")
        if param_value == SPECIAL_PARAM_STRUCTURE:
            selected_value = str(form.cleaned_data.get("options") or "").strip()
            display_name = humanize_identifier(selected_value)
            return {
                "id": f"special:structure:{selected_value}",
                "score_param_name": "structure",
                "name": selected_value,
                "type": "special",
                "special_key": "structure_source",
                "special_value": selected_value,
                "display_name": display_name,
            }
        if param_value == SPECIAL_PARAM_EC_NUMBER:
            selected_value = str(form.cleaned_data.get("text_value") or "").strip()
            return {
                "id": f"special:ec:{selected_value}",
                "score_param_name": "ec_number",
                "name": selected_value,
                "type": "special",
                "special_key": "ec_filter",
                "special_value": selected_value,
                "display_name": selected_value,
            }
        if param_value == SPECIAL_PARAM_GO_TERM:
            selected_value = str(form.cleaned_data.get("text_value") or "").strip()
            return {
                "id": f"special:go:{selected_value}",
                "score_param_name": "go_term",
                "name": selected_value,
                "type": "special",
                "special_key": "go_filter",
                "special_value": selected_value,
                "display_name": selected_value,
            }
        return None

    if request.method == "POST":
        if "finish_process" in request.POST:
            set_workspace_session_value(
                request.session, request.user, "selected_parameters", selected_parameters
            )
            return redirect_with_query("tpwebapp:protein_list")

        if "reset_process" in request.POST:
            pop_workspace_session_value(request.session, request.user, "selected_parameters", None)
            return redirect_with_query("tpwebapp:parameterformview")

        remove_filter_id = request.POST.get("remove_filter")
        if remove_filter_id:
            selected_parameters = [
                selected
                for selected in selected_parameters
                if str(selected.get("id")) != str(remove_filter_id)
            ]
            set_workspace_session_value(
                request.session, request.user, "selected_parameters", selected_parameters
            )
            return redirect_with_query("tpwebapp:parameterformview")

        if parameterform.is_valid():
            raw_param_value = parameterform.cleaned_data.get("param")
            if raw_param_value in {SPECIAL_PARAM_STRUCTURE, SPECIAL_PARAM_EC_NUMBER, SPECIAL_PARAM_GO_TERM}:
                filter_payload = build_special_filter_payload(parameterform)
            else:
                score_param = parameterform.cleaned_data.get("resolved_param")
                if score_param_kind(score_param) == "numeric":
                    filter_payload = build_numeric_filter_payload(parameterform)
                else:
                    selected_option = parameterform.cleaned_data.get("resolved_option")
                    filter_payload = selected_option.to_dict() if selected_option else None

            if filter_payload:
                if filter_payload in selected_parameters:
                    duplicate_filter = True
                else:
                    selected_parameters.append(filter_payload)
                    set_workspace_session_value(
                        request.session, request.user, "selected_parameters", selected_parameters
                    )
                    return redirect_with_query("tpwebapp:parameterformview")

    display_parameters = []
    for selected in selected_parameters:
        score_param_name = selected.get("score_param_name", "")
        option_name = selected.get("name", "")
        display_param_name = humanize_identifier(score_param_name)
        if str(selected.get("type") or "").lower() in {"numeric", "special"}:
            display_option_name = selected.get("display_name", "")
        else:
            display_option_name = humanize_identifier(option_name)
        display_parameters.append(
            {
                **selected,
                "display_score_param_name": display_param_name or score_param_name,
                "display_name": display_option_name or option_name,
            }
        )

    active_option_ids = [str(selected.get("id")) for selected in selected_parameters if selected.get("id")]
    param_type_map = {
        str(score_param.id): score_param_kind(score_param)
        for score_param in visible_score_params_queryset(request.user)
    }

    if request.GET.get("export") == "view_csv":
        sections = [
            {
                "title": "Advanced filters",
                "headers": ["Field", "Value"],
                "rows": [
                    ["Genome", display_genome_name(assembly_name)],
                    ["Active filters", len(display_parameters)],
                    ["Search query", request.GET.get("search", "").strip()],
                    ["Score formula", request.GET.get("scoreformula", "").strip()],
                    ["Rows per page", request.GET.get("pageSize", "").strip()],
                ],
            },
            {
                "title": "Selected filters",
                "headers": ["Parameter", "Value"],
                "rows": [
                    [item.get("display_score_param_name", ""), item.get("display_name", "")]
                    for item in display_parameters
                ],
            },
        ]
        return xlsx_sections_response(f"{assembly_name}-advanced-filters", sections)

    return render(
        request,
        "search/parameterform.html",
        {
            "form": parameterform,
            "parameters": display_parameters,
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "genome": genome_url_slug(assembly_name),
            "active_filter_count": len(selected_parameters),
            "duplicate_filter": duplicate_filter,
            "active_option_ids": ",".join(active_option_ids),
            "param_type_map": param_type_map,
            "structure_source": structure_source,
            "structure_source_choices": structure_source_choices,
            "ec_filter_value": ec_filter_value,
            "search_query": request.GET.get("search", "").strip(),
            "scoreformula": request.GET.get("scoreformula", "").strip(),
            "page_size": request.GET.get("pageSize", "").strip(),
            "annotation_kind": annotation_kind,
            "annotation_value": annotation_value,
            "view_export_url": "?export=view_csv",
            "ec_explorer_url": reverse(
                "tpwebapp:annotation_explorer",
                kwargs={"genome": genome_url_slug(assembly_name), "annotation_kind": "ec"},
            ),
        },
    )

def load_options(request):
    param_id = request.GET.get("param")
    options = []
    if param_id == SPECIAL_PARAM_STRUCTURE:
        options = [
            {"id": "experimental", "label": "Experimental"},
            {"id": "alphafold", "label": "AlphaFold"},
            {"id": "colabfold", "label": "ColabFold"},
            {"id": "none", "label": "No structure"},
        ]
    elif param_id in {SPECIAL_PARAM_EC_NUMBER, SPECIAL_PARAM_GO_TERM}:
        options = []
    elif param_id:
        options = [
            {"id": option.id, "label": humanize_identifier(option.name) or option.name}
            for option in visible_score_param_options_queryset(request.user, param_id)
        ]
    return render(request, "search/parameter_options.html", {"options": options})


def reset_filters(request, genome=None):
    pop_workspace_session_value(request.session, request.user, "selected_parameters", None)
    if genome:
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        return redirect("tpwebapp:protein_list", genome=genome_url_slug(assembly_name))
    return redirect("tpwebapp:index")

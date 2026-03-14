from django.shortcuts import render, redirect
from django.http import Http404
from tpweb.views.ParameterForm import ParameterForm, humanize_identifier
from tpweb.services.genome_workspace import display_genome_name, user_can_access_genome_name
from tpweb.services.score_params import visible_score_param_options_queryset
from tpweb.services.workspace import (
    get_workspace_session_value,
    pop_workspace_session_value,
    set_workspace_session_value,
)


def ParameterFormView(request, assembly_name):
    if not user_can_access_genome_name(request.user, assembly_name):
        raise Http404("Genome not found")
    selected_parameters = get_workspace_session_value(
        request.session, request.user, "selected_parameters", []
    )
    parameterform = ParameterForm(request.POST or None, user=request.user)
    duplicate_filter = False

    if request.method == "POST":
        if "finish_process" in request.POST:
            set_workspace_session_value(
                request.session, request.user, "selected_parameters", selected_parameters
            )
            return redirect("tpwebapp:protein_list", assembly_name=assembly_name)

        if "reset_process" in request.POST:
            pop_workspace_session_value(request.session, request.user, "selected_parameters", None)
            return redirect("tpwebapp:parameterformview", assembly_name=assembly_name)

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
            return redirect("tpwebapp:parameterformview", assembly_name=assembly_name)

        if parameterform.is_valid():
            selected_option = parameterform.cleaned_data.get("options")
            if selected_option:
                option_payload = selected_option.to_dict()
                if option_payload in selected_parameters:
                    duplicate_filter = True
                else:
                    selected_parameters.append(option_payload)
                    set_workspace_session_value(
                        request.session, request.user, "selected_parameters", selected_parameters
                    )
                    return redirect("tpwebapp:parameterformview", assembly_name=assembly_name)

    display_parameters = []
    for selected in selected_parameters:
        score_param_name = selected.get("score_param_name", "")
        option_name = selected.get("name", "")
        display_param_name = humanize_identifier(score_param_name)
        display_option_name = humanize_identifier(option_name)
        display_parameters.append(
            {
                **selected,
                "display_score_param_name": display_param_name or score_param_name,
                "display_name": display_option_name or option_name,
            }
        )

    active_option_ids = [str(selected.get("id")) for selected in selected_parameters if selected.get("id")]

    return render(
        request,
        "search/parameterform.html",
        {
            "form": parameterform,
            "parameters": display_parameters,
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "active_filter_count": len(selected_parameters),
            "duplicate_filter": duplicate_filter,
            "active_option_ids": ",".join(active_option_ids),
        },
    )

def load_options(request):
    param_id = request.GET.get("param")
    options = []
    if param_id:
        options = [
            {"id": option.id, "label": humanize_identifier(option.name) or option.name}
            for option in visible_score_param_options_queryset(request.user, param_id)
        ]
    return render(request, "search/parameter_options.html", {"options": options})


def reset_filters(request, assembly_name=None):
    pop_workspace_session_value(request.session, request.user, "selected_parameters", None)
    if assembly_name:
        return redirect("tpwebapp:protein_list", assembly_name=assembly_name)
    return redirect("tpwebapp:index")

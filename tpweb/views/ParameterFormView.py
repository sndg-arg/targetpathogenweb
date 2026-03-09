from django.shortcuts import render, redirect
from tpweb.views.ParameterForm import ParameterForm, humanize_identifier
from tpweb.models.ScoreParam import ScoreParamOptions


def ParameterFormView(request, assembly_name):
    selected_parameters = request.session.get("selected_parameters", [])
    parameterform = ParameterForm(request.POST or None)
    duplicate_filter = False

    if request.method == "POST":
        if "finish_process" in request.POST:
            request.session["selected_parameters"] = selected_parameters
            return redirect("tpwebapp:protein_list", assembly_name=assembly_name)

        if "reset_process" in request.POST:
            request.session.pop("selected_parameters", None)
            return redirect("tpwebapp:parameterformview", assembly_name=assembly_name)

        remove_filter_id = request.POST.get("remove_filter")
        if remove_filter_id:
            selected_parameters = [
                selected
                for selected in selected_parameters
                if str(selected.get("id")) != str(remove_filter_id)
            ]
            request.session["selected_parameters"] = selected_parameters
            return redirect("tpwebapp:parameterformview", assembly_name=assembly_name)

        if parameterform.is_valid():
            selected_option = parameterform.cleaned_data.get("options")
            if selected_option:
                option_payload = selected_option.to_dict()
                if option_payload in selected_parameters:
                    duplicate_filter = True
                else:
                    selected_parameters.append(option_payload)
                    request.session["selected_parameters"] = selected_parameters
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
            for option in ScoreParamOptions.objects.filter(score_param_id=param_id).order_by("name")
        ]
    return render(request, "search/parameter_options.html", {"options": options})


def reset_filters(request, assembly_name=None):
    request.session.pop("selected_parameters", None)
    if assembly_name:
        return redirect("tpwebapp:protein_list", assembly_name=assembly_name)
    return redirect("tpwebapp:index")

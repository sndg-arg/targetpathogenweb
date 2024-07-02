from django.shortcuts import render, redirect
from tpweb.views.ParameterForm import ParameterForm
from django.views import View
from tpweb.models.ScoreParam import ScoreParamOptions

def ParameterFormView(request, assembly_name):
    if 'selected_parameters' not in request.session.keys():
        selected_parameters = []
    else:
        selected_parameters = request.session['selected_parameters']

    if request.method == "POST":
        if 'finish_process' in request.POST:
            # User wants to finish the process
            request.session['selected_parameters'] = selected_parameters
            return redirect(f'../../assembly/{assembly_name}/protein')
        else:
            # Add new parameters
            parameterform = ParameterForm(request.POST)
            if parameterform.is_valid():
                selected_parameters.append(parameterform.cleaned_data["options"].to_dict())
                request.session['selected_parameters'] = selected_parameters
            else:
                print(parameterform.errors)
    else:
        parameterform = ParameterForm()

    return render(request, 'search/parameterform.html', {"form": parameterform})

def load_options(request):
    param_id = request.GET.get("param")
    options = ScoreParamOptions.objects.filter(score_param_id = param_id)
    return render(request, "search/parameter_options.html", {"options": options})

def reset_filters(request, assembly_name=None):
    request.session.pop('selected_parameters', None)
    return redirect(f'../../assembly/{assembly_name}/protein')

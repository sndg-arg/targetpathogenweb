from django.shortcuts import render, redirect
from tpweb.views.ParameterForm import ParameterForm
from django.views import View
from tpweb.models.ScoreParam import ScoreParamOptions

def ParameterFormView(request, assembly_name):

    if request.method == "POST":
        parameterform = ParameterForm(request.POST)
        if parameterform .is_valid():
            request.session['selected_parameters'] = parameterform.cleaned_data["options"].to_dict()
            return redirect(f'../../assembly/{assembly_name}/protein') 
        else:
            print(parameterform.errors)
    else:
        parameterform = ParameterForm()
    return render(request, 'search/parameterform.html', {"form": parameterform})

def load_options(request):
    param_id = request.GET.get("param")
    options = ScoreParamOptions.objects.filter(score_param_id = param_id)
    return render(request, "search/parameter_options.html", {"options": options})

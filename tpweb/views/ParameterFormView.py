from django.shortcuts import render
from tpweb.views.ParameterForm import ParameterForm
from django.views import View
from tpweb.models.ScoreParam import ScoreParamOptions

def ParameterFormView(request):
    if request.method == "POST":
        parameterform = ParameterForm(request.POST)
        if parameterform .is_valid():
            print(parameterform.cleaned_data["param"])
            print(parameterform.cleaned_data["options"])
        else:
            print(parameterform.errors)
    else:
        parameterform = ParameterForm()
    return render(request, 'search/parameterform.html', {"form": parameterform})

def load_options(request):
    param_id = request.GET.get("param")
    options = ScoreParamOptions.objects.filter(score_param_id = param_id)
    return render(request, "search/parameter_options.html", {"options": options})

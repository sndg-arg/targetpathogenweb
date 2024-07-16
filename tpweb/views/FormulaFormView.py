from django.shortcuts import render, redirect
from tpweb.models import TPUser
from tpweb.views.FormulaForm import FormulaForm
from django.views import View
from tpweb.models.ScoreParam import ScoreParamOptions, ScoreParam
from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
from django.urls import reverse
def FormulaFormView(request, assembly_name):
    def current_formula_string(self):
        terms = {}
        for t in self.terms.all():
            if t.score_param.name in terms:
                terms[t.score_param.name].append(t)
            else:
                terms[t.score_param.name] = [t]
        terms2 = {}
        for param_name, ts in terms.items():
            for t in ts:
                terms2[t.value] = t.coefficient
        result = ""
        for i, (key, value) in enumerate(terms2.items()):
            if int(value) < 0:
                result += f"({value}) x {key}"
            else:
                result += f"{value} x {key}"
            if i < len(terms2) - 1:
                result += " + "
        formuladto = f"{self.name} = {result}"
        return formuladto

    def add_new_formula(formulaname, formulacoefficient):
        user = TPUser.objects.get(id=request.user.id)
        new_formula = ScoreFormula.objects.get_or_create(name=f'{formulaname}',user=user)
        new_formula_id = ScoreFormulaParam.objects.filter(formula = new_formula[0]).delete()
        for term in formulacoefficient:
            formula = ScoreFormula.objects.get(name=f'{formulaname}')
            param = ScoreParam.objects.get(id=term['param'])
            option = ScoreParamOptions.objects.get(id=term['option'])
            coefficient = term['coefficient']
            ScoreFormulaParam.objects.get_or_create(formula=formula ,operation="=",coefficient=coefficient ,value=option ,score_param=param)

    if 'current_formula' not in request.session.keys():
        current_formula = []
    else:
        current_formula = request.session['current_formula']

    if request.method == "POST":
        if 'reset_process' in request.POST:
            request.session['current_formula'] = []
            return redirect(f"./{assembly_name}")
        if 'finish_process' in request.POST:
            if 'current_formula' in request.session.keys():
                add_new_formula(request.session['formulaname'], request.session['current_formula'])
                request.session.pop('current_formula')
            return redirect(f'../../assembly/{assembly_name}/protein')
        formulaform = FormulaForm(request.POST)
        formulaname = formulaform.data["new_formula_name"]
        formulaparam = formulaform.data["param"]
        formulaoption = formulaform.data["options"]
        formulacoefficient = formulaform.data["coefficient"]
        if formulaform.is_valid():
            if any(d['param'] == formulaparam and d['option'] == formulaoption for d in current_formula):
                request.session.pop('current_formula')
                return redirect(reverse("tpwebapp:formula_form", kwargs={"assembly_name": assembly_name}) + '?error_message=Select+only+ONE+coefficient+per+parameter+option!. ¡Try Again!')
            term_dict = {"param": formulaparam, "option": formulaoption, "coefficient": formulacoefficient}
            current_formula.append(term_dict)
            request.session['current_formula'] = current_formula
            request.session['formulaname'] = formulaname
            print(request.session['current_formula'])
        else:
            #print(formulaform.errors)
            pass
    else:
        formulaform = FormulaForm()
        formulaname = ""
    return render(request, 'search/formulaform.html', { "form": formulaform,
                                                        "parameters": current_formula,
                                                        "name": formulaname})


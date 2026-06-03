from django.shortcuts import render, redirect
from django.urls import reverse

from tpweb.models import TPUser
from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
from tpweb.models.ScoreParam import ScoreParamOptions, ScoreParam
from tpweb.views.FormulaForm import FormulaForm

def FormulaFormView(request, assembly_name):

    def current_formula_string(formula, formulaname):
        if not formula:
            return "Start assigning coefficients to make the new formula"

        option_ids = [term.get("option") for term in formula if term.get("option")]
        option_map = {
            str(opt.id): str(opt)
            for opt in ScoreParamOptions.objects.filter(id__in=option_ids)
        }

        terms = []
        for term in formula:
            coefficient_raw = term.get("coefficient", "")
            try:
                coefficient_value = float(coefficient_raw)
                coefficient_label = f"{coefficient_value:g}"
            except (TypeError, ValueError):
                coefficient_value = None
                coefficient_label = str(coefficient_raw)

            option_name = option_map.get(
                str(term.get("option")),
                f"Option {term.get('option', '?')}",
            )
            if coefficient_value is not None and coefficient_value < 0:
                terms.append(f"({coefficient_label}) x {option_name}")
            else:
                terms.append(f"{coefficient_label} x {option_name}")

        prefix = f"{formulaname} = " if formulaname else ""
        return prefix + " + ".join(terms)

    def build_preview_terms(formula):
        if not formula:
            return []

        option_ids = [term.get("option") for term in formula if term.get("option")]
        param_ids = [term.get("param") for term in formula if term.get("param")]

        option_map = {
            str(opt.id): opt.name
            for opt in ScoreParamOptions.objects.filter(id__in=option_ids)
        }
        param_map = {
            str(param.id): param.name
            for param in ScoreParam.objects.filter(id__in=param_ids)
        }

        preview = []
        for index, term in enumerate(formula, start=1):
            coefficient_raw = term.get("coefficient", "")
            try:
                coefficient_label = f"{float(coefficient_raw):g}"
            except (TypeError, ValueError):
                coefficient_label = str(coefficient_raw)

            preview.append({
                "index": index,
                "param_name": param_map.get(str(term.get("param")), "Unknown parameter"),
                "option_name": option_map.get(str(term.get("option")), "Unknown option"),
                "coefficient": coefficient_label,
            })
        return preview

    def add_new_formula(formulaname, formulacoefficient):
        if not formulaname:
            return

        user = TPUser.objects.get(id=request.user.id)
        formula_obj, _ = ScoreFormula.objects.get_or_create(name=formulaname, user=user)
        ScoreFormulaParam.objects.filter(formula=formula_obj).delete()

        for term in formulacoefficient:
            param_id = term.get("param")
            option_id = term.get("option")
            coefficient = term.get("coefficient")
            if not (param_id and option_id):
                continue
            try:
                param = ScoreParam.objects.get(id=param_id)
                option = ScoreParamOptions.objects.get(id=option_id)
            except (ScoreParam.DoesNotExist, ScoreParamOptions.DoesNotExist):
                continue
            ScoreFormulaParam.objects.get_or_create(
                formula=formula_obj,
                operation="=",
                coefficient=coefficient,
                value=option,
                score_param=param,
            )

    current_formula = request.session.get("current_formula", [])
    if not isinstance(current_formula, list):
        current_formula = []
    formulaname = request.session.get("formulaname", "")
    formulaform = FormulaForm(initial={"new_formula_name": formulaname})

    if request.method == "POST":
        if "reset_process" in request.POST:
            request.session.pop("current_formula", None)
            request.session.pop("formulaname", None)
            return redirect(reverse("tpwebapp:formula_form", kwargs={"assembly_name": assembly_name}))

        if "remove_last_term" in request.POST:
            if current_formula:
                current_formula.pop()
                request.session["current_formula"] = current_formula
            return redirect(reverse("tpwebapp:formula_form", kwargs={"assembly_name": assembly_name}))

        if "finish_process" in request.POST:
            if current_formula and formulaname:
                add_new_formula(formulaname, current_formula)
            request.session.pop("current_formula", None)
            request.session.pop("formulaname", None)
            return redirect(reverse("tpwebapp:protein_list", kwargs={"assembly_name": assembly_name}))

        formulaform = FormulaForm(request.POST)
        formulaname = formulaform.data.get("new_formula_name", "").strip()
        formulaparam = formulaform.data.get("param")
        formulaoption = formulaform.data.get("options")
        formulacoefficient = formulaform.data.get("coefficient")
        if formulaform.is_valid():
            request.session["formulaname"] = formulaname
            if any(d["param"] == formulaparam and d["option"] == formulaoption for d in current_formula):
                return redirect(
                    reverse("tpwebapp:formula_form", kwargs={"assembly_name": assembly_name})
                    + "?error_message=Select+only+ONE+coefficient+per+parameter+option!.+Try+Again!"
                )
            term_dict = {"param": formulaparam, "option": formulaoption, "coefficient": formulacoefficient}
            current_formula.append(term_dict)
            request.session["current_formula"] = current_formula
        else:
            print(formulaform.errors)

    current_formula = request.session.get("current_formula", current_formula)
    formulaname = request.session.get("formulaname", formulaname)
    preview_terms = build_preview_terms(current_formula)

    return render(
        request,
        "search/formulaform.html",
        {
            "form": formulaform,
            "parameters": current_formula_string(current_formula, formulaname),
            "formula_name": formulaname,
            "preview_terms": preview_terms,
            "term_count": len(preview_terms),
            "assembly_name": assembly_name,
        },
    )

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.services.formula_evaluator import available_variables_grouped, validate_expression_syntax
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, resolve_genome_from_slug
from tpweb.services.workspace import resolve_workspace_user
from tpweb.views.FormulaForm import FormulaForm

SAFE_FUNCTIONS = [
    {"label": "sqrt(x)", "insert": "sqrt()", "desc": "Square root"},
    {"label": "log(x)", "insert": "log()", "desc": "Natural logarithm"},
    {"label": "log2(x)", "insert": "log2()", "desc": "Log base 2"},
    {"label": "log10(x)", "insert": "log10()", "desc": "Log base 10"},
    {"label": "exp(x)", "insert": "exp()", "desc": "Exponential e^x"},
    {"label": "abs(x)", "insert": "abs()", "desc": "Absolute value"},
    {"label": "pow(x,n)", "insert": "pow(,)", "desc": "Power x^n"},
    {"label": "max(a,b)", "insert": "max(,)", "desc": "Maximum"},
    {"label": "min(a,b)", "insert": "min(,)", "desc": "Minimum"},
    {"label": "floor(x)", "insert": "floor()", "desc": "Round down"},
    {"label": "ceil(x)", "insert": "ceil()", "desc": "Round up"},
    {"label": "round(x)", "insert": "round()", "desc": "Round to nearest integer"},
]


def FormulaFormView(request, genome):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")

    user = resolve_workspace_user(request.user)
    variable_groups = available_variables_grouped(user)

    if request.method == "POST":
        if "reset_process" in request.POST:
            return redirect(reverse("tpwebapp:formula_form", kwargs={"genome": genome_url_slug(assembly_name)}))

        form = FormulaForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["formula_name"].strip()
            expression = form.cleaned_data["expression"].strip()

            validation = validate_expression_syntax(expression, user=user)
            if not validation["valid"]:
                form.add_error("expression", validation["error"] or "Invalid expression")
            else:
                formula_obj, _ = ScoreFormula.objects.update_or_create(
                    name=name,
                    user=user,
                    defaults={"expression": expression},
                )
                return redirect(
                    reverse("tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)})
                    + f"?scoreformula={name}"
                )
    else:
        form = FormulaForm()

    return render(
        request,
        "search/formulaform.html",
        {
            "form": form,
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "genome": genome_url_slug(assembly_name),
            "variable_groups": variable_groups,
            "safe_functions": SAFE_FUNCTIONS,
        },
    )

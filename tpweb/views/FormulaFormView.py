from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.services.formula_evaluator import available_variables_grouped, validate_expression_syntax
from tpweb.services.score_params import genome_score_param_names
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.visibility_settings import (
    VISIBILITY_PRIVATE,
    formula_visibility,
    set_formula_visibility,
)
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

EXAMPLE_FORMULAS = [
    {
        "label": "Druggability + essentiality",
        "expression": "0.7 * druggability + 2 * hit_in_deg_y",
        "desc": "Use raw pocket druggability and reward DEG essentiality hits.",
    },
    {
        "label": "Penalize human similarity",
        "expression": "druggability + 2 * hit_in_deg_y - 0.02 * human_identity",
        "desc": "Keep druggability high while lowering rank for human sequence identity.",
    },
    {
        "label": "Off-target aware",
        "expression": "druggability + hit_in_deg_y - gut_microbiome_offtarget_hit - human_offtarget_hit",
        "desc": "Combine pocket score with binary off-target indicators.",
    },
]


@login_required
@permission_required("tpweb.can_manage_formulas", raise_exception=True)
def FormulaFormView(request, genome):
    assembly_name = resolve_genome_from_slug(request.user, genome)
    if not assembly_name:
        raise Http404("Genome not found")

    user = resolve_workspace_user(request.user)
    # Only variables this genome has values for -- an empty set (nothing
    # loaded yet) falls back to the full palette rather than an empty one.
    hidden_variables = []
    variable_groups = available_variables_grouped(
        user,
        genome_param_names=genome_score_param_names(assembly_name) or None,
        hidden=hidden_variables,
    )

    # Edit mode: ?edit=<pk> (GET) / editing_pk (POST) on one of the user's own
    # expression-based formulas. Term-based legacy formulas (no expression)
    # can't round-trip through the expression editor, so they're not editable.
    editing_pk = request.POST.get("editing_pk") or request.GET.get("edit")
    editing = None
    if editing_pk and str(editing_pk).isdigit():
        editing = (
            ScoreFormula.objects.filter(pk=editing_pk, user=user)
            .exclude(expression__isnull=True)
            .exclude(expression="")
            .first()
        )

    if request.method == "POST":
        if "reset_process" in request.POST:
            return redirect(
                reverse("tpwebapp:formula_form", kwargs={"genome": genome_url_slug(assembly_name)})
            )

        form = FormulaForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["formula_name"].strip()
            expression = form.cleaned_data["expression"].strip()

            validation = validate_expression_syntax(expression, user=user)
            name_taken = (
                ScoreFormula.objects.filter(name=name, user=user)
                .exclude(pk=getattr(editing, "pk", None))
                .exists()
            )
            if not validation["valid"]:
                form.add_error("expression", validation["error"] or "Invalid expression")
            elif editing and name_taken:
                form.add_error("formula_name", "You already have another formula with this name.")
            else:
                if editing:
                    editing.name = name
                    editing.expression = expression
                    editing.save(update_fields=["name", "expression"])
                    formula_obj = editing
                else:
                    formula_obj, _ = ScoreFormula.objects.update_or_create(
                        name=name,
                        user=user,
                        defaults={"expression": expression},
                    )
                visibility = form.cleaned_data.get("visibility") or VISIBILITY_PRIVATE
                set_formula_visibility(formula_obj, user, visibility)
                return redirect(
                    reverse(
                        "tpwebapp:protein_list", kwargs={"genome": genome_url_slug(assembly_name)}
                    )
                    + f"?scoreformula={name}"
                )
    elif editing:
        form = FormulaForm(
            initial={
                "formula_name": editing.name,
                "expression": editing.expression,
                "visibility": formula_visibility(editing),
            }
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
            # Only uploaded columns: structure/pocket IDs are covered by the
            # generic note on the page, and listing them is just noise.
            "hidden_variables": [h for h in hidden_variables if h["category"] == "Custom"],
            "safe_functions": SAFE_FUNCTIONS,
            "example_formulas": EXAMPLE_FORMULAS,
            "editing": editing,
        },
    )

import re

from django.db.models import Q

from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.workspace import resolve_workspace_user


def _dedupe_formulas_by_name(formulas):
    unique = []
    seen_names = set()
    for formula in formulas:
        name_key = (formula.name or "").strip().casefold()
        if not name_key or name_key in seen_names:
            continue
        seen_names.add(name_key)
        unique.append(formula)
    return unique


def resolve_formulas_for_user(user):
    workspace_user = resolve_workspace_user(user)
    formulas = list(
        ScoreFormula.objects.filter(user=workspace_user).order_by("-default", "name", "id")
    )
    if not formulas:
        formulas = list(
            ScoreFormula.objects.filter((Q(default=True) | Q(public=True)) & Q(user__isnull=True))
            .distinct()
            .order_by("-default", "name", "id")
        )
    return _dedupe_formulas_by_name(formulas)


NO_FORMULA_SENTINEL = "__none__"


def choose_formula(formulas, requested_formula_name):
    requested_name = (requested_formula_name or "").strip()
    if requested_name == NO_FORMULA_SENTINEL:
        return None
    if requested_name:
        selected = [formula for formula in formulas if formula.name == requested_name]
        if selected:
            return selected[0]

    default_formula = [formula for formula in formulas if formula.default]
    if default_formula:
        return default_formula[0]
    return None


def build_col_descriptions(formula_term_list):
    descriptions = {}
    for term in formula_term_list:
        choices = list(term.score_param.choices.all())
        choice_names = "-".join(choice.name for choice in choices)
        choice_details = ". ".join(
            f"{choice.name}: {choice.description}" for choice in choices if choice.description
        )
        descriptions[term.score_param.name] = (
            f"{term.score_param.description}. Possible values: {choice_names}. {choice_details}"
        )
    return descriptions


def build_all_term_descriptions():
    """Return a {token: description} dict covering every ScoreParam column name
    and every categorical ScoreParamOptions value site-wide.

    Unlike build_col_descriptions() (scoped to one formula's own
    ScoreFormulaParam terms), this is independent of which formula is active
    or whether a formula even has term rows at all -- expression-based
    formulas (free-text .expression, e.g. "Kp score") have no
    ScoreFormulaParam rows to scope a per-formula lookup from, so a global
    dict is the only way to explain their raw column-name tokens too.
    """
    descriptions = {}
    for param in ScoreParam.objects.all().prefetch_related("choices"):
        if param.description:
            descriptions[param.name] = param.description
        for choice in param.choices.all():
            if choice.description:
                descriptions[choice.name] = choice.description
    return descriptions


def annotate_formula_terms(expression, term_descriptions):
    """Return "token: description · token: description" for every whole-word
    token in *expression* that matches a key in *term_descriptions*.

    Not a full expression parser -- these are known, finite identifier sets
    (ScoreParam/ScoreParamOptions names), so a word-boundary scan is enough
    to recognize them inside free-text formula expressions without needing
    to understand the surrounding arithmetic.
    """
    if not expression or not term_descriptions:
        return ""
    found = []
    seen = set()
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", expression):
        token = match.group(0)
        if token in seen:
            continue
        description = term_descriptions.get(token)
        if not description:
            continue
        seen.add(token)
        found.append(f"{token}: {description}")
    return " · ".join(found)


def ordered_score_params(formula_term_list):
    ordered = []
    seen_score_param_ids = set()
    for term in formula_term_list:
        if term.score_param_id in seen_score_param_ids:
            continue
        seen_score_param_ids.add(term.score_param_id)
        ordered.append(term.score_param)
    return ordered


def build_score_dict_and_columns(ordered_params):
    columns = ["Score"]
    score_dict = {}
    for score_param in ordered_params:
        score_dict[score_param.name] = score_param
        columns.append(score_param.name)
    return score_dict, columns


def coefficient_map(formula_term_list):
    coefficient_by_param = {}
    for term in formula_term_list:
        coefficient_by_param.setdefault(term.score_param.name, {})[
            term.value
        ] = term.coefficient
    return coefficient_by_param


def formula_to_dto(formula, description_by_param):
    terms = {}
    for term in formula.terms.all():
        terms.setdefault(term.score_param.name, []).append(term)

    dto_terms = []
    for param_name, param_terms in terms.items():
        if len(param_terms) == 1:
            term = param_terms[0]
            dto_terms.append(
                {
                    "coefficient": term.coefficient,
                    "param": term.score_param.name,
                    "desc": description_by_param[term.score_param.name],
                }
            )
            continue

        multi_desc = " ".join(
            [f"{term.coefficient} if {term.value} " for term in param_terms]
        )
        dto_terms.append(
            {
                "coefficient": 1,
                "param": param_name,
                "desc": multi_desc,
            }
        )

    return {"name": formula.name, "terms": dto_terms}

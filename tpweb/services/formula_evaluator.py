"""
Safe mathematical expression evaluator for scoring formulas.

Variables are built from per-protein ScoreParamValues:
  druggability = the raw numeric Druggability value if the parameter is numeric
  human_identity = the raw numeric identity value if the parameter is numeric
  human_offtarget_hit = 1.0 if human_offtarget == "hit", else 0.0
  ...

Supported operators: + - * / ^ ** %
Supported functions: sqrt log log2 log10 exp abs max min pow floor ceil round
"""

import ast
import math
import operator
import re

SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "max": max,
    "min": min,
    "pow": math.pow,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
}

_SAFE_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
)


FORMULA_PALETTE_MAX_CATEGORICAL_OPTIONS = 25


def normalize_var_name(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def safe_eval_expression(expr_str: str, variables: dict) -> float:
    """Evaluate a math expression string. Raises ValueError on any problem."""
    normalized = expr_str.replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"Unsupported operation: {type(node).__name__}")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, int | float):
                raise ValueError("Only numeric literals are allowed")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in SAFE_FUNCTIONS:
                return SAFE_FUNCTIONS[node.id]
            if node.id in variables:
                return float(variables[node.id])
            raise ValueError(f"Unknown variable: '{node.id}'")
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            _ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.Pow: operator.pow,
                ast.Mod: operator.mod,
                ast.FloorDiv: operator.floordiv,
            }
            op_fn = _ops.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_fn(left, right)
        if isinstance(node, ast.UnaryOp):
            val = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -val
            return val
        if isinstance(node, ast.Call):
            func = _eval(node.func)
            if not callable(func):
                raise ValueError("Expression contains a non-callable call target")
            args = [_eval(a) for a in node.args]
            try:
                return float(func(*args))
            except Exception as exc:
                raise ValueError(f"Function call error: {exc}") from exc
        raise ValueError(f"Unsupported node: {type(node).__name__}")

    return _eval(tree)


class ZeroCache(dict):
    """{variable: 0.0} plus the ids of the ScoreParams the user may read, so
    build_expression_variables() can ignore everything else. A protein's
    score_params include other users' private uploaded columns; without this a
    formula that happened to name one would be scored with its values."""

    visible_param_ids = None


def build_all_options_zero(user=None):
    """Return {variable_name: 0.0} for every visible variable for *user*.

    Call once per formula evaluation batch; pass the result to
    build_expression_variables() for each protein.
    """
    from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
    from django.db.models import Q
    from tpweb.services.score_param_types import is_numeric_score_param
    from tpweb.services.score_params import score_param_visibility_filter

    if user is not None:
        param_visibility = score_param_visibility_filter(user)
        option_visibility = Q(score_param__in=ScoreParam.objects.filter(param_visibility))
    else:
        param_visibility = Q(user__isnull=True)
        option_visibility = Q(score_param__user__isnull=True)

    cache = ZeroCache()
    params = list(ScoreParam.objects.filter(param_visibility).order_by("category", "name", "id"))
    if user is not None:
        cache.visible_param_ids = {param.pk for param in params}
    for param in params:
        if is_numeric_score_param(param):
            pk = normalize_var_name(param.name)
            if pk:
                cache[pk] = 0.0

    qs = ScoreParamOptions.objects.select_related("score_param").filter(option_visibility)
    for opt in qs:
        pk = normalize_var_name(opt.score_param.name)
        vk = normalize_var_name(opt.name)
        if pk and vk:
            cache[f"{pk}_{vk}"] = 0.0
    return cache


def build_expression_variables(protein, zero_cache: dict) -> dict:
    """Build per-protein variable dict with categorical indicators and numeric values."""
    from tpweb.services.score_param_types import is_numeric_score_param

    variables = dict(zero_cache)
    visible_param_ids = getattr(zero_cache, "visible_param_ids", None)
    for spv in protein.score_params.all():
        if visible_param_ids is not None and spv.score_param_id not in visible_param_ids:
            continue
        pk = normalize_var_name(spv.score_param.name)
        if not pk:
            continue
        if is_numeric_score_param(spv.score_param):
            if spv.numeric_value is not None:
                variables[pk] = float(spv.numeric_value)
                continue
            try:
                variables[pk] = float(str(spv.value).replace(",", "."))
            except (TypeError, ValueError):
                variables[pk] = 0.0
            continue
        vk = normalize_var_name(spv.value or "")
        if vk:
            variables[f"{pk}_{vk}"] = 1.0
    return variables


def _is_numeric_option(name: str) -> bool:
    """Return True if the option name is just a raw number (not a meaningful category)."""
    try:
        float(name.replace(",", "."))
        return True
    except ValueError:
        return False


def available_variables_grouped(
    user=None,
    max_categorical_options=FORMULA_PALETTE_MAX_CATEGORICAL_OPTIONS,
    genome_param_names=None,
):
    """Return variables grouped by ScoreParam category for the UI palette.

    The evaluator still knows every visible categorical option through
    build_all_options_zero(). This palette intentionally hides very large
    categorical fields, such as one option per PDB/AF structure, because those
    are useful as filters but make the formula builder unusable.
    """
    from tpweb.models.ScoreParam import ScoreParam
    from tpweb.services.score_param_types import is_numeric_score_param
    from tpweb.services.score_params import score_param_visibility_filter

    if user is not None:
        param_qs = (
            ScoreParam.objects.filter(score_param_visibility_filter(user))
            .prefetch_related("choices")
            .order_by("category", "name")
        )
    else:
        param_qs = (
            ScoreParam.objects.filter(user__isnull=True)
            .prefetch_related("choices")
            .order_by("category", "name")
        )

    groups = {}
    for param in param_qs:
        # genome_param_names (see score_params.genome_score_param_names): only
        # offer variables this genome actually has values for.
        if genome_param_names is not None and param.name not in genome_param_names:
            continue
        cat = param.category or "Other"
        pname = normalize_var_name(param.name)
        if is_numeric_score_param(param):
            if pname:
                desc = param.description or f"{param.name} raw numeric value"
                groups.setdefault(cat, []).append(
                    {"var": pname, "desc": desc, "kind": "numeric", "param": param.name}
                )
            continue
        if not pname:
            continue
        palette_options = []
        for opt in param.choices.all():
            if _is_numeric_option(opt.name):
                continue
            vname = normalize_var_name(opt.name)
            if vname:
                palette_options.append((opt, vname))
        if len(palette_options) > max_categorical_options:
            continue
        for opt, vname in palette_options:
            var = f"{pname}_{vname}"
            desc = opt.description or f"{param.name} = {opt.name}"
            groups.setdefault(cat, []).append(
                {"var": var, "desc": desc, "kind": "categorical", "param": param.name}
            )
    return groups


def formula_uses_missing_params(formula, genome_param_names, var_to_param):
    """True if `formula` relies on a ScoreParam with no values in this genome.

    Expression formulas are checked token by token against the palette's
    variable -> param map (`var_to_param`, from available_variables_grouped);
    term-based formulas against their terms' params directly."""
    expression = (getattr(formula, "expression", "") or "").strip()
    if expression:
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression):
            param_name = var_to_param.get(token.lower())
            if param_name and param_name not in genome_param_names:
                return True
        return False
    return any(term.score_param.name not in genome_param_names for term in formula.terms.all())


def validate_expression_syntax(expr_str: str, user=None) -> dict:
    """Validate an expression string. Returns {valid: bool, error: str|None}."""
    if not expr_str.strip():
        return {"valid": False, "error": "Expression is empty"}
    zero_cache = build_all_options_zero(user)
    try:
        result = safe_eval_expression(expr_str, zero_cache)
        if not isinstance(result, float) or result != result:  # NaN check
            return {"valid": False, "error": "Expression produces NaN"}
        return {"valid": True, "error": None}
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        return {"valid": False, "error": str(exc)}
    except Exception as exc:
        return {"valid": False, "error": f"Evaluation error: {exc}"}

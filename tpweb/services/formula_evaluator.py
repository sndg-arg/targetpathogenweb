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
    "sqrt":   math.sqrt,
    "log":    math.log,
    "log2":   math.log2,
    "log10":  math.log10,
    "exp":    math.exp,
    "abs":    abs,
    "max":    max,
    "min":    min,
    "pow":    math.pow,
    "floor":  math.floor,
    "ceil":   math.ceil,
    "round":  round,
}

_SAFE_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call,
    ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    ast.Mod, ast.FloorDiv,
    ast.USub, ast.UAdd,
)


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
            if not isinstance(node.value, (int, float)):
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
                ast.Add:      operator.add,
                ast.Sub:      operator.sub,
                ast.Mult:     operator.mul,
                ast.Div:      operator.truediv,
                ast.Pow:      operator.pow,
                ast.Mod:      operator.mod,
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


def build_all_options_zero(user=None):
    """Return {variable_name: 0.0} for every visible variable for *user*.

    Call once per formula evaluation batch; pass the result to
    build_expression_variables() for each protein.
    """
    from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
    from django.db.models import Q
    from tpweb.services.score_param_types import is_numeric_score_param
    from tpweb.services.workspace import resolve_workspace_user

    if user is not None:
        workspace_user = resolve_workspace_user(user)
        param_visibility = Q(user__isnull=True) | Q(user=workspace_user)
        option_visibility = Q(score_param__user__isnull=True) | Q(score_param__user=workspace_user)
    else:
        param_visibility = Q(user__isnull=True)
        option_visibility = Q(score_param__user__isnull=True)

    cache = {}
    params = ScoreParam.objects.filter(param_visibility).order_by("category", "name", "id")
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
    for spv in protein.score_params.all():
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


def available_variables_grouped(user=None):
    """Return variables grouped by ScoreParam category for the UI palette."""
    from tpweb.models.ScoreParam import ScoreParam
    from django.db.models import Q
    from tpweb.services.score_param_types import is_numeric_score_param
    from tpweb.services.workspace import resolve_workspace_user

    if user is not None:
        workspace_user = resolve_workspace_user(user)
        param_qs = ScoreParam.objects.filter(
            Q(user__isnull=True) | Q(user=workspace_user)
        ).prefetch_related("choices").order_by("category", "name")
    else:
        param_qs = ScoreParam.objects.filter(
            user__isnull=True
        ).prefetch_related("choices").order_by("category", "name")

    groups = {}
    for param in param_qs:
        cat = param.category or "Other"
        pname = normalize_var_name(param.name)
        if is_numeric_score_param(param):
            if pname:
                desc = param.description or f"{param.name} raw numeric value"
                groups.setdefault(cat, []).append({"var": pname, "desc": desc, "kind": "numeric"})
            continue
        for opt in param.choices.all():
            if _is_numeric_option(opt.name):
                continue
            vname = normalize_var_name(opt.name)
            if not vname:
                continue
            var = f"{pname}_{vname}"
            desc = opt.description or f"{param.name} = {opt.name}"
            groups.setdefault(cat, []).append({"var": var, "desc": desc, "kind": "categorical"})
    return groups


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

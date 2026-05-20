from tpweb.services.protein_annotations import protein_annotation_summary
from tpweb.services.protein_list import humanize_identifier
from tpweb.services.structure_sources import summarize_structure_sources


def _display_table_value(value):
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return "-"
    if text.replace(".", "", 1).isdigit():
        return text
    return humanize_identifier(text) or text


def score_param_value_map(protein):
    from tpweb.services.score_param_types import is_numeric_score_param

    values = {}
    for spv in protein.score_params.all():
        if is_numeric_score_param(spv.score_param):
            if spv.numeric_value is not None:
                values[spv.score_param.name] = spv.numeric_value
                continue
            try:
                values[spv.score_param.name] = float(str(spv.value).replace(",", "."))
            except (TypeError, ValueError):
                values[spv.score_param.name] = None
            continue
        values[spv.score_param.name] = spv.value
    return values


def compute_score_value(param_values, coefficient_by_param):
    score_value = 0
    weights = {}
    for param_name, param_value in param_values.items():
        contribution = coefficient_by_param.get(param_name, {}).get(param_value)
        if contribution is None:
            continue
        score_value += contribution
        weights[param_name] = round(contribution, 2)
    return score_value, weights


def compute_expression_score(protein, expression, zero_cache):
    from tpweb.services.formula_evaluator import build_expression_variables, safe_eval_expression
    variables = build_expression_variables(protein, zero_cache)
    try:
        return float(safe_eval_expression(expression, variables)), {}
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0, {}


def build_protein_table_row(protein, visible_columns, coefficient_by_param,
                             expression=None, zero_cache=None):
    param_values = score_param_value_map(protein)
    table_data = {
        name: _display_table_value(value)
        for name, value in param_values.items()
        if name in visible_columns
    }
    if expression and zero_cache is not None:
        score_value, weights = compute_expression_score(protein, expression, zero_cache)
    else:
        score_value, weights = compute_score_value(param_values, coefficient_by_param)

    table_data["Score"] = round(score_value, 2)
    genes = [gene for gene in protein.genes() if len(gene) <= 6]
    top_factors = sorted(weights.items(), key=lambda factor: abs(factor[1]), reverse=True)[:3]
    top_factors_text = (
        ", ".join([f"{name}: {value:g}" for name, value in top_factors])
        if top_factors
        else "No weighted terms"
    )
    structure_summary = summarize_structure_sources(protein.structures.all())
    ec_summary = protein_annotation_summary(protein, "ec", limit=3)
    go_summary = protein_annotation_summary(protein, "go", limit=3)
    ec_badges = ec_summary["badges"]
    go_badges = go_summary["badges"]

    row = {
        "id": protein.bioentry_id,
        "accession": protein.accession,
        "genes": genes,
        "name": protein.name,
        "description": protein.description,
        "score": score_value,
        "genes_text": ", ".join(genes) if genes else "-",
        "top_factors_text": top_factors_text,
        "structure_source": structure_summary["source"],
        "structure_source_label": structure_summary["label"],
        "structure_count": structure_summary["count"],
        "ec_badges": ec_badges,
        "ec_text": ", ".join(b["accession"] for b in ec_badges) or "-",
        "ec_total": ec_summary["total"],
        "ec_remaining": ec_summary["remaining"],
        "go_badges": go_badges,
        "go_text": ", ".join(b["accession"] for b in go_badges) or "-",
        "go_total": go_summary["total"],
        "go_remaining": go_summary["remaining"],
        "has_structure": structure_summary["has_structure"],
    }
    return row, table_data, weights

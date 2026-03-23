from tpweb.services.protein_annotations import protein_annotation_badges, protein_annotation_text
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
    return {spv.score_param.name: spv.value for spv in protein.score_params.all()}


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


def build_protein_table_row(protein, visible_columns, coefficient_by_param):
    param_values = score_param_value_map(protein)
    table_data = {
        name: _display_table_value(value)
        for name, value in param_values.items()
        if name in visible_columns
    }
    score_value, weights = compute_score_value(param_values, coefficient_by_param)

    table_data["Score"] = score_value
    genes = [gene for gene in protein.genes() if len(gene) <= 6]
    top_factors = sorted(weights.items(), key=lambda factor: abs(factor[1]), reverse=True)[:3]
    top_factors_text = (
        ", ".join([f"{name}: {value:g}" for name, value in top_factors])
        if top_factors
        else "No weighted terms"
    )
    structure_summary = summarize_structure_sources(protein.structures.all())
    ec_badges = protein_annotation_badges(protein, "ec", limit=3)
    go_badges = protein_annotation_badges(protein, "go", limit=3)

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
        "ec_text": protein_annotation_text(protein, "ec", limit=3),
        "go_badges": go_badges,
        "go_text": protein_annotation_text(protein, "go", limit=3),
    }
    return row, table_data, weights

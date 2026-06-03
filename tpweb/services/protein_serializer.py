def build_protein_table_row(protein, visible_columns, coefficient_by_param):
    param_values = {spv.score_param.name: spv.value for spv in protein.score_params.all()}
    table_data = {
        name: value for name, value in param_values.items() if name in visible_columns
    }
    weights = {}
    score_value = 0

    for param_name, param_value in param_values.items():
        contribution = coefficient_by_param.get(param_name, {}).get(param_value)
        if contribution is None:
            continue
        score_value += contribution
        weights[param_name] = round(contribution, 2)

    table_data["Score"] = score_value
    genes = [gene for gene in protein.genes() if len(gene) <= 6]
    top_factors = sorted(weights.items(), key=lambda factor: abs(factor[1]), reverse=True)[:3]
    top_factors_text = (
        ", ".join([f"{name}: {value:g}" for name, value in top_factors])
        if top_factors
        else "No weighted terms"
    )

    row = {
        "id": protein.bioentry_id,
        "accession": protein.accession,
        "genes": genes,
        "name": protein.name,
        "description": protein.description,
        "score": score_value,
        "genes_text": ", ".join(genes) if genes else "-",
        "top_factors_text": top_factors_text,
    }
    return row, table_data, weights


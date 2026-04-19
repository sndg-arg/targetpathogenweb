STRUCTURE_SOURCE_NONE = "none"
STRUCTURE_SOURCE_EXPERIMENTAL = "experimental"
STRUCTURE_SOURCE_ALPHAFOLD = "alphafold"
STRUCTURE_SOURCE_COLABFOLD = "colabfold"
STRUCTURE_SOURCE_MODEL = "model"
STRUCTURE_SOURCE_MIXED = "mixed"

PDB_EXPERIMENT_ALPHAFOLD = "AF"
PDB_EXPERIMENT_COLABFOLD = "CF"
PDB_MODEL_EXPERIMENTS = (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
)

STRUCTURE_SOURCE_LABELS = {
    STRUCTURE_SOURCE_NONE: "Unavailable",
    STRUCTURE_SOURCE_EXPERIMENTAL: "Experimental",
    STRUCTURE_SOURCE_ALPHAFOLD: "AlphaFold",
    STRUCTURE_SOURCE_COLABFOLD: "ColabFold",
    STRUCTURE_SOURCE_MODEL: "Model",
    STRUCTURE_SOURCE_MIXED: "Experimental + AlphaFold",
}

STRUCTURE_SOURCE_CHOICES = (
    (STRUCTURE_SOURCE_NONE, "No structure"),
    (STRUCTURE_SOURCE_EXPERIMENTAL, "Experimental"),
    (STRUCTURE_SOURCE_ALPHAFOLD, "AlphaFold"),
    (STRUCTURE_SOURCE_COLABFOLD, "ColabFold"),
    (STRUCTURE_SOURCE_MODEL, "Model"),
    (STRUCTURE_SOURCE_MIXED, "Experimental + AlphaFold"),
)


def _normalize_experiment(experiment):
    return str(experiment or "").strip().upper()


def classify_structure_experiment(experiment):
    normalized = _normalize_experiment(experiment)
    if not normalized:
        return STRUCTURE_SOURCE_MODEL
    if normalized == PDB_EXPERIMENT_COLABFOLD or "COLABFOLD" in normalized:
        return STRUCTURE_SOURCE_COLABFOLD
    if normalized == PDB_EXPERIMENT_ALPHAFOLD or "ALPHAFOLD" in normalized:
        return STRUCTURE_SOURCE_ALPHAFOLD
    return STRUCTURE_SOURCE_EXPERIMENTAL


def structure_source_label(source_key):
    return STRUCTURE_SOURCE_LABELS.get(source_key, STRUCTURE_SOURCE_LABELS[STRUCTURE_SOURCE_MODEL])


def summarize_structure_sources(structures):
    source_keys = set()
    total_structures = 0

    for structure in structures or []:
        pdb = getattr(structure, "pdb", structure)
        source_keys.add(classify_structure_experiment(getattr(pdb, "experiment", "")))
        total_structures += 1

    if not source_keys:
        primary_source = STRUCTURE_SOURCE_NONE
    elif len(source_keys) == 1:
        primary_source = next(iter(source_keys))
    elif source_keys == {STRUCTURE_SOURCE_EXPERIMENTAL, STRUCTURE_SOURCE_ALPHAFOLD}:
        primary_source = STRUCTURE_SOURCE_MIXED
    else:
        primary_source = STRUCTURE_SOURCE_MODEL

    ordered_sources = [
        source
        for source in (
            STRUCTURE_SOURCE_EXPERIMENTAL,
            STRUCTURE_SOURCE_ALPHAFOLD,
            STRUCTURE_SOURCE_COLABFOLD,
            STRUCTURE_SOURCE_MODEL,
        )
        if source in source_keys
    ]

    return {
        "source": primary_source,
        "label": structure_source_label(primary_source),
        "labels": [structure_source_label(source) for source in ordered_sources],
        "has_structure": bool(source_keys),
        "count": total_structures,
    }

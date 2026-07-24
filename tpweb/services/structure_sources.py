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
    STRUCTURE_SOURCE_ALPHAFOLD: "AlphaFold DB model",
    STRUCTURE_SOURCE_COLABFOLD: "ColabFold model",
    STRUCTURE_SOURCE_MODEL: "Model",
    STRUCTURE_SOURCE_MIXED: "Experimental + predicted",
}

STRUCTURE_SOURCE_CHOICES = (
    (STRUCTURE_SOURCE_NONE, "No structure"),
    (STRUCTURE_SOURCE_EXPERIMENTAL, "Experimental"),
    (STRUCTURE_SOURCE_ALPHAFOLD, "AlphaFold DB model"),
    (STRUCTURE_SOURCE_COLABFOLD, "ColabFold model"),
    (STRUCTURE_SOURCE_MODEL, "Model"),
    (STRUCTURE_SOURCE_MIXED, "Experimental + predicted"),
)


_STRUCTURE_PREFERENCE = {"EX": 0, "AF": 1, "CF": 2}
_STRUCTURE_TOGGLE_LABELS = {
    "EX": "Crystal structure",
    "AF": "AlphaFold DB model",
    "CF": "ColabFold model",
}


def structure_toggle_label(experiment):
    return _STRUCTURE_TOGGLE_LABELS.get((experiment or "").upper(), "Model")


def chain_selector(chain):
    """PyMOL/NGL-style chain selector fragment, e.g. ':A' or 'polymer' when
    no chain is set. Was copy-pasted identically in ProteinView.py and
    StructureView.py; lives here since both views already depend on this
    module."""
    chain = (chain or "").strip()
    return f":{chain}" if chain else "polymer"


def _structure_coverage_span(link):
    start = getattr(link, "uniprot_start", None)
    end = getattr(link, "uniprot_end", None)
    if start is None or end is None:
        return 0
    return max(0, end - start + 1)


def _structure_resolution_value(link):
    pdb = getattr(link, "pdb", None)
    value = getattr(link, "resolution", None) or getattr(pdb, "resolution", None)
    try:
        resolution = float(value)
        return 999.0 if resolution == 20 else resolution
    except (TypeError, ValueError):
        return 999.0


def sort_structures_by_preference(structures):
    def key(link):
        pdb = getattr(link, "pdb", None)
        experiment = (getattr(pdb, "experiment", "") or "").upper()
        return (
            _STRUCTURE_PREFERENCE.get(experiment, 9),
            -_structure_coverage_span(link),
            _structure_resolution_value(link),
            str(getattr(pdb, "code", "") or ""),
        )

    return sorted(structures, key=key)


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
    elif STRUCTURE_SOURCE_EXPERIMENTAL in source_keys:
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

    source_labels = [structure_source_label(source) for source in ordered_sources]
    combined_label = " + ".join(source_labels) if source_labels else structure_source_label(STRUCTURE_SOURCE_NONE)

    return {
        "source": primary_source,
        "label": combined_label,
        "labels": source_labels,
        "has_structure": bool(source_keys),
        "count": total_structures,
    }


def structure_identifier_candidates(identifier):
    """Expand a bare structure identifier into the code variants it may appear as.

    An imported score value like "A0A0H3GWB0" may match a PDB.code of
    "AF_A0A0H3GWB0" or "CB_A0A0H3GWB0" (or the reverse: a stored "AF_..."
    identifier should still match the bare accession). Shared by ProteinView's
    "selected pocket evidence" display and the pocket-size-outlier indexer, so
    both resolve a curated structure identifier the same way.
    """
    ident = (identifier or "").strip().upper()
    if not ident:
        return set()
    candidates = {ident}
    for prefix in ("AF_", "CB_"):
        if ident.startswith(prefix):
            candidates.add(ident[len(prefix):])
    candidates.add(f"AF_{ident}")
    candidates.add(f"CB_{ident}")
    return candidates


def structure_matches_identifier(link, identifier):
    """Does `link` (a BioentryStructure, or a PDB itself) refer to `identifier`?"""
    if link is None:
        return False
    pdb = getattr(link, "pdb", link)
    code = (getattr(pdb, "code", "") or "").strip().upper()
    return any(
        code == candidate or code.startswith(f"{candidate}_") or code.startswith(f"{candidate}-")
        for candidate in structure_identifier_candidates(identifier)
    )

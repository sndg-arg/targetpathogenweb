import re


GENOME_METADATA_LABELS = {
    "EntryLength": "Sequence length [bp]",
    "COUNT_gene": "Gene features",
    "COUNT_CDS": "Protein-coding features",
    "COUNT_tRNA": "tRNA features",
    "COUNT_rRNA": "rRNA features",
    "COUNT_ncRNA": "ncRNA features",
    "COUNT_tmRNA": "tmRNA features",
    "COUNT_EC": "EC annotated proteins",
    "COUNT_EXPERIMENTAL": "Experimental structures",
    "COUNT_STRUCTS": "3D structures",
}

# Same sentinel assembly_overview.py's _build_fact() already uses for the hero
# chips on this page -- a curated/external import can leave a field genuinely
# unpopulated (stored as a literal "0"/"0.0"), which should read as missing
# data, not as a real zero value.
_MISSING_VALUE_SENTINELS = (None, "", "0", "0.0")

GENOME_METADATA_ORDER = {
    key: index
    for index, key in enumerate(
        (
            "EntryLength",
            "COUNT_gene",
            "COUNT_CDS",
            "COUNT_tRNA",
            "COUNT_rRNA",
            "COUNT_ncRNA",
            "COUNT_tmRNA",
            "COUNT_EC",
            "COUNT_EXPERIMENTAL",
        )
    )
}


def genome_metadata_label(key):
    normalized = str(key or "").strip()
    if not normalized:
        return ""
    if normalized in GENOME_METADATA_LABELS:
        return GENOME_METADATA_LABELS[normalized]

    text = re.sub(r"[_-]+", " ", normalized)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else normalized


def build_genome_metadata_rows(props):
    props = props or {}
    rows = [
        {
            "key": key,
            "label": genome_metadata_label(key),
            "value": "—" if value in _MISSING_VALUE_SENTINELS else value,
        }
        for key, value in props.items()
    ]
    rows.sort(key=lambda row: (GENOME_METADATA_ORDER.get(row["key"], 999), row["label"].lower()))
    return rows

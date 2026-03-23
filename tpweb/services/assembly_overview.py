import re

from tpweb.services.genome_workspace import describe_genome_scope


def _parse_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_int(value):
    if value is None:
        return None
    return f"{value:,}"


def _format_bp(value):
    if value is None:
        return None
    return f"{value:,} bp"


def _record_type_from_description(description):
    text = str(description or "").lower()
    if "chromosome" in text:
        return "Chromosome"
    if "plasmid" in text:
        return "Plasmid"
    if "contig" in text:
        return "Contig"
    return "Genome"


def _completion_from_description(description):
    text = str(description or "").lower()
    if "complete genome" in text:
        return "Complete genome"
    if "complete sequence" in text:
        return "Complete sequence"
    if "draft genome" in text:
        return "Draft genome"
    return None


def _organism_from_description(description):
    text = str(description or "").strip()
    if not text:
        return None

    lowered = text.lower()
    strain_idx = lowered.find(" strain ")
    if strain_idx > 0:
        return text[:strain_idx].strip(" ,")

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None

    tokens = parts[0].split()
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    return parts[0]


def _strain_from_description(description):
    text = str(description or "").strip()
    if not text:
        return None

    match = re.search(r"\bstrain\s+(.+?)(?:\s+(chromosome|plasmid|contig)\b|,\s|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None

    tokens = parts[0].split()
    if len(tokens) > 2:
        return " ".join(tokens[2:]).strip() or None
    return None


def _build_fact(label, value):
    if value in (None, "", "0", "0.0"):
        return None
    return {
        "label": label,
        "value": value,
    }


def build_assembly_overview(user, genome_name, description, props, workspace_metrics=None):
    props = props or {}
    workspace_metrics = workspace_metrics or {}
    scope = describe_genome_scope(user, genome_name)
    gene_count = _parse_int(props.get("COUNT_gene"))
    source_cds_count = _parse_int(props.get("COUNT_CDS"))
    cds_count = workspace_metrics.get("total_proteins")
    if cds_count is None:
        cds_count = source_cds_count
    trna_count = _parse_int(props.get("COUNT_tRNA"))
    rrna_count = _parse_int(props.get("COUNT_rRNA"))
    ncrna_count = _parse_int(props.get("COUNT_ncRNA"))
    tmrna_count = _parse_int(props.get("COUNT_tmRNA"))
    entry_length = _parse_int(props.get("EntryLength"))

    rna_total = sum(value or 0 for value in [trna_count, rrna_count, ncrna_count, tmrna_count]) or None
    untranslated_cds_count = None
    if source_cds_count is not None and cds_count is not None and source_cds_count >= cds_count:
        untranslated_cds_count = source_cds_count - cds_count

    hero_facts = [
        _build_fact("Source", scope["label"]),
        _build_fact("Organism", _organism_from_description(description)),
        _build_fact("Strain", _strain_from_description(description)),
        _build_fact("Record", _record_type_from_description(description)),
        _build_fact("Completion", _completion_from_description(description)),
        _build_fact("Sequence length", _format_bp(entry_length)),
        _build_fact("Annotated features", _format_int(gene_count)),
    ]
    hero_facts = [fact for fact in hero_facts if fact]
    hero_fact_map = {fact["label"]: fact for fact in hero_facts}

    primary_hero_facts = [
        hero_fact_map[label]
        for label in ["Source", "Organism", "Sequence length", "Annotated features"]
        if label in hero_fact_map
    ]
    secondary_hero_facts = [
        hero_fact_map[label]
        for label in ["Strain", "Record", "Completion"]
        if label in hero_fact_map
    ]

    loaded_feature_facts = [
        _build_fact("Protein-coding loaded", _format_int(cds_count)),
        _build_fact("CDS without protein sequence", _format_int(untranslated_cds_count)),
        _build_fact("RNA features", _format_int(rna_total)),
        _build_fact("tRNA", _format_int(trna_count)),
        _build_fact("rRNA", _format_int(rrna_count)),
    ]
    loaded_feature_facts = [fact for fact in loaded_feature_facts if fact]

    composition_facts = [
        _build_fact("Source coding features", _format_int(source_cds_count)),
        _build_fact("Protein-coding loaded", _format_int(cds_count)),
        _build_fact("CDS without protein sequence", _format_int(untranslated_cds_count)),
        _build_fact("RNA features", _format_int(rna_total)),
        _build_fact("tRNA", _format_int(trna_count)),
        _build_fact("rRNA", _format_int(rrna_count)),
    ]
    composition_facts = [fact for fact in composition_facts if fact]

    return {
        "scope": scope,
        "hero_facts": hero_facts,
        "primary_hero_facts": primary_hero_facts,
        "secondary_hero_facts": secondary_hero_facts,
        "loaded_feature_facts": loaded_feature_facts,
        "composition_facts": composition_facts,
        "feature_count_display": _format_int(gene_count),
        "gene_count_display": _format_int(gene_count),
        "strain_display": _strain_from_description(description),
        "record_display": _record_type_from_description(description),
        "completion_display": _completion_from_description(description),
        "source_cds_display": _format_int(source_cds_count),
        "protein_coding_display": _format_int(cds_count),
        "untranslated_cds_display": _format_int(untranslated_cds_count),
        "rna_total_display": _format_int(rna_total),
    }

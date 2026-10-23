"""Overview / Function / Sequence / Cross-refs context for a human protein.

Reads the `HumanProtein` JSON content parsed at ingest time
(`import_human_curated_proteins`) and shapes it for
`human_target/templates/human/human_protein.html`. Mirrors the "build one context
dict, delegate the shaping" style of `protein_summary.py`, but has no
pipeline/genome-workspace/druggability inputs -- those are bacteria-pipeline
concepts that don't apply here (see CLAUDE.md "Human Targets").
"""

from __future__ import annotations

import re

# UniProt cross-reference database name -> display bucket. Anything not
# listed here falls into "Other" -- this mirrors target-human-web's
# XREF_GROUPS grouping, kept as a flat dict (not a class) since it's pure
# lookup data.
XREF_GROUPS = {
    "Structure": {"PDB", "PDBsum", "SMR", "AlphaFoldDB", "BMRB", "EMDB", "ModBase"},
    "Family & domains": {
        "Pfam",
        "InterPro",
        "PROSITE",
        "SUPFAM",
        "Gene3D",
        "PANTHER",
        "PRINTS",
        "SMART",
        "CDD",
        "HAMAP",
        "PIRSF",
    },
    "Sequence": {"EMBL", "RefSeq", "CCDS", "PIR", "UniGene"},
    "Genome annotation": {
        "Ensembl",
        "GeneID",
        "KEGG",
        "UCSC",
        "MANE-Select",
        "GenomeRNAi",
    },
    "Organism databases": {"HGNC", "MIM", "neXtProt", "CTD", "DisGeNET", "GeneCards"},
    "Expression": {"Bgee", "ExpressionAtlas", "CleanEx", "Genevisible"},
    "Phylogenomics": {
        "eggNOG",
        "InParanoid",
        "OMA",
        "OrthoDB",
        "PhylomeDB",
        "TreeFam",
        "GeneTree",
        "HOGENOM",
    },
    "Proteomic": {"PaxDb", "PRIDE", "ProteomicsDB", "EPD", "jPOST", "MassIVE"},
}
_XREF_DB_TO_GROUP = {db: group for group, dbs in XREF_GROUPS.items() for db in dbs}
XREF_GROUP_ORDER = [
    "Structure",
    "Family & domains",
    "Sequence",
    "Genome annotation",
    "Organism databases",
    "Expression",
    "Phylogenomics",
    "Proteomic",
    "Other",
]

_GO_ASPECT_LABELS = {
    "P": "Biological process",
    "C": "Cellular component",
    "F": "Molecular function",
}


_PAREN = re.compile(r"\s*\(([^()]*)\)")
_PUBMED = re.compile(r"^(PubMed:\d+|ECO:\d+)$")


def strip_citations(text):
    """UniProt prose without its inline evidence lists, e.g. "(PubMed:123,
    PubMed:456)"; other parentheticals such as "(By similarity)" stay. The
    papers themselves are listed under References."""

    def keep(match):
        parts = [part.strip() for part in match.group(1).split(",")]
        kept = [part for part in parts if part and not _PUBMED.match(part)]
        if len(kept) == len(parts):
            return match.group(0)
        return f" ({', '.join(kept)})" if kept else ""

    return _PAREN.sub(keep, text or "").strip()


def _first_sentence(text):
    text = (text or "").strip()
    if not text:
        return ""
    for sep in (". ", ".\n"):
        if sep in text:
            return text.split(sep, 1)[0].strip() + "."
    return text


def build_human_overview_context(human_protein):
    hp = human_protein
    score = hp.annotation_score or 0
    return {
        "summary_sentence": _first_sentence(strip_citations(hp.function_text)),
        "quick_facts": [
            {"label": "Length", "value": f"{hp.sequence_length} aa" if hp.sequence_length else "—"},
            {"label": "Mass", "value": f"{hp.mass_da:,} Da" if hp.mass_da else "—"},
            {
                "label": "Annotation score",
                "value": f"{score:.0f}/5" if hp.annotation_score is not None else "—",
            },
            {"label": "Entry version", "value": hp.entry_version or "—"},
        ],
        "caution_text": strip_citations(hp.caution_text),
        "subunit_text": strip_citations(hp.subunit_text),
        "polymorphism_text": hp.polymorphism_text,
        "publications": hp.publications or [],
        "lineage": hp.lineage or [],
        "lineage_rail": [*(hp.lineage or []), hp.organism_name or "Homo sapiens"],
        "keywords": hp.keywords or [],
        "subcellular_locations": hp.subcellular_locations or [],
        "is_reviewed": hp.is_reviewed,
        "chromosome": hp.chromosome,
    }


def build_human_function_context(human_protein):
    hp = human_protein
    go_by_aspect = {"P": [], "C": [], "F": []}
    for term in hp.go_terms or []:
        aspect = str(term.get("aspect") or "").strip().upper()
        if aspect in go_by_aspect:
            go_by_aspect[aspect].append(term)
    go_cards = [
        {
            "aspect": aspect,
            "label": _GO_ASPECT_LABELS[aspect],
            "terms": go_by_aspect[aspect],
        }
        for aspect in ("P", "C", "F")
        if go_by_aspect[aspect]
    ]
    # Caution/subunit/subcellular-location/polymorphism are already shown on
    # the Overview tab -- kept off this context to avoid duplicating the
    # same text in two sections.
    return {
        "function_text": strip_citations(hp.function_text),
        "catalytic_activity": hp.catalytic_activity or [],
        "go_cards": go_cards,
    }


# Feature types drawn on the architecture map, by row. Anything else stays
# in the feature table only.
_TOPOLOGY_TYPES = {"Topological domain", "Transmembrane", "Intramembrane"}
_DOMAIN_TYPES = {"Domain", "Repeat", "Zinc finger", "DNA binding"}
_SITE_TYPES = {"Active site", "Binding site", "Site"}
_PTM_TYPES = {"Modified residue", "Glycosylation", "Lipidation", "Cross-link", "Disulfide bond"}
_VARIANT_TYPES = {"Natural variant"}
SEQUENCE_LINE = 60
SEQUENCE_BLOCK = 10


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _topology_kind(feature):
    if feature.get("type") != "Topological domain":
        return "membrane"
    text = (feature.get("description") or "").lower()
    if "extracell" in text or "lumenal" in text:
        return "outside"
    if "cytoplasm" in text:
        return "inside"
    return "other"


def _ruler(length):
    for step in (10, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        if length / step <= 10:
            break
    return [
        {"position": position, "left": round(position / length * 100, 3)}
        for position in range(step, length, step)
    ]


def build_human_architecture(features, length):
    """Positions (as % of the sequence) for the protein architecture map:
    topology and signal peptide on the backbone, domains on top, and one tick
    row each for sites, modifications and natural variants."""
    length = _int(length)
    if not length:
        return None

    def placed(feature):
        start, end = _int(feature.get("start")), _int(feature.get("end"))
        if start is None:
            return None
        start = max(1, start)
        end = max(start, min(end if end is not None else start, length))
        return {
            "type": feature.get("type", ""),
            "description": feature.get("description") or feature.get("type", ""),
            "start": start,
            "end": end,
            "left": round((start - 1) / length * 100, 3),
            "width": round((end - start + 1) / length * 100, 3),
        }

    rows = {"topology": [], "signal": [], "domains": [], "sites": [], "ptms": [], "variants": []}
    for feature in features or []:
        kind = feature.get("type", "")
        item = placed(feature)
        if item is None:
            continue
        if kind in _TOPOLOGY_TYPES:
            item["kind"] = _topology_kind(feature)
            rows["topology"].append(item)
        elif kind == "Signal":
            rows["signal"].append(item)
        elif kind in _DOMAIN_TYPES:
            rows["domains"].append(item)
        elif kind in _SITE_TYPES:
            rows["sites"].append(item)
        elif kind in _PTM_TYPES:
            rows["ptms"].append(item)
        elif kind in _VARIANT_TYPES:
            rows["variants"].append(item)
    if not any(rows.values()):
        return None
    tick_rows = [
        {"key": key, "label": label, "items": rows[key]}
        for key, label in (
            ("sites", "Sites"),
            ("ptms", "Modifications"),
            ("variants", "Natural variants"),
        )
        if rows[key]
    ]
    return {
        "length": length,
        "topology": rows["topology"],
        "signal": rows["signal"],
        "domains": rows["domains"],
        "tick_rows": tick_rows,
        "ruler": _ruler(length),
        "has_topology": bool(rows["topology"]),
    }


def format_sequence(sequence):
    """UniProt-style layout: lines of 60 residues in blocks of 10, each block
    tagged with its first position (1-based) so a range can be highlighted."""
    sequence = (sequence or "").strip()
    lines = []
    for line_start in range(0, len(sequence), SEQUENCE_LINE):
        line = sequence[line_start : line_start + SEQUENCE_LINE]
        lines.append(
            {
                "start": line_start + 1,
                "blocks": [
                    {
                        "start": line_start + offset + 1,
                        "text": line[offset : offset + SEQUENCE_BLOCK],
                    }
                    for offset in range(0, len(line), SEQUENCE_BLOCK)
                ],
            }
        )
    return lines


def build_human_sequence_context(human_protein):
    hp = human_protein
    lanes = {"Signal": [], "Chain": [], "Domain": [], "Region": [], "Disulfide bond": []}
    for feature in hp.features_raw or []:
        ftype = feature.get("type", "")
        if ftype in lanes:
            lanes[ftype].append(feature)
    length = hp.sequence_length or len(hp.sequence or "")
    return {
        "sequence": hp.sequence,
        "sequence_length": hp.sequence_length,
        "sequence_lines": format_sequence(hp.sequence),
        "architecture": build_human_architecture(hp.features_raw, length),
        "feature_lanes": [
            {"type": ftype, "features": features} for ftype, features in lanes.items() if features
        ],
        "features_raw": hp.features_raw or [],
    }


def build_human_xref_context(human_protein):
    grouped = {group: [] for group in XREF_GROUP_ORDER}
    for xref in human_protein.cross_references_raw or []:
        db = xref.get("database", "")
        # GO terms are already shown with real names, grouped by aspect, on the
        # Function tab (build_human_function_context) -- showing them again here
        # as bare unlabeled IDs in the "Other" catch-all would just duplicate
        # that, worse.
        if db == "GO":
            continue
        group = _XREF_DB_TO_GROUP.get(db, "Other")
        grouped[group].append(xref)
    return {
        "groups": [
            {"label": group, "items": grouped[group]}
            for group in XREF_GROUP_ORDER
            if grouped[group]
        ],
    }

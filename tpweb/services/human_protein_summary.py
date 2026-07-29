"""Overview / Function / Sequence / Cross-refs context for a human protein.

Reads the `HumanProtein` JSON content parsed at ingest time
(`import_human_curated_proteins`) and shapes it for
`tpweb/templates/human/human_protein.html`. Mirrors the "build one context
dict, delegate the shaping" style of `protein_summary.py`, but has no
pipeline/genome-workspace/druggability inputs -- those are bacteria-pipeline
concepts that don't apply here (see CLAUDE.md "Human Targets").
"""
from __future__ import annotations

# UniProt cross-reference database name -> display bucket. Anything not
# listed here falls into "Other" -- this mirrors target-human-web's
# XREF_GROUPS grouping, kept as a flat dict (not a class) since it's pure
# lookup data.
XREF_GROUPS = {
    "Structure": {"PDB", "PDBsum", "SMR", "AlphaFoldDB", "BMRB", "EMDB", "ModBase"},
    "Family & domains": {
        "Pfam", "InterPro", "PROSITE", "SUPFAM", "Gene3D", "PANTHER",
        "PRINTS", "SMART", "CDD", "HAMAP", "PIRSF",
    },
    "Sequence": {"EMBL", "RefSeq", "CCDS", "PIR", "UniGene"},
    "Genome annotation": {
        "Ensembl", "GeneID", "KEGG", "UCSC", "MANE-Select", "GenomeRNAi",
    },
    "Organism databases": {"HGNC", "MIM", "neXtProt", "CTD", "DisGeNET", "GeneCards"},
    "Expression": {"Bgee", "ExpressionAtlas", "CleanEx", "Genevisible"},
    "Phylogenomics": {
        "eggNOG", "InParanoid", "OMA", "OrthoDB", "PhylomeDB", "TreeFam",
        "GeneTree", "HOGENOM",
    },
    "Proteomic": {"PaxDb", "PRIDE", "ProteomicsDB", "EPD", "jPOST", "MassIVE"},
}
_XREF_DB_TO_GROUP = {
    db: group for group, dbs in XREF_GROUPS.items() for db in dbs
}
XREF_GROUP_ORDER = [
    "Structure", "Family & domains", "Sequence", "Genome annotation",
    "Organism databases", "Expression", "Phylogenomics", "Proteomic", "Other",
]

_GO_ASPECT_LABELS = {
    "P": "Biological process",
    "C": "Cellular component",
    "F": "Molecular function",
}


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
        "summary_sentence": _first_sentence(hp.function_text),
        "quick_facts": [
            {"label": "Length", "value": f"{hp.sequence_length} aa" if hp.sequence_length else "—"},
            {"label": "Mass", "value": f"{hp.mass_da:,} Da" if hp.mass_da else "—"},
            {"label": "Annotation score", "value": f"{score:.0f}/5" if hp.annotation_score is not None else "—"},
            {"label": "Entry version", "value": hp.entry_version or "—"},
        ],
        "caution_text": hp.caution_text,
        "subunit_text": hp.subunit_text,
        "polymorphism_text": hp.polymorphism_text,
        "publications": hp.publications or [],
        "lineage": hp.lineage or [],
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
        "function_text": hp.function_text,
        "catalytic_activity": hp.catalytic_activity or [],
        "go_cards": go_cards,
    }


def build_human_sequence_context(human_protein):
    hp = human_protein
    lanes = {"Signal": [], "Chain": [], "Domain": [], "Region": [], "Disulfide bond": []}
    for feature in hp.features_raw or []:
        ftype = feature.get("type", "")
        if ftype in lanes:
            lanes[ftype].append(feature)
    return {
        "sequence": hp.sequence,
        "sequence_length": hp.sequence_length,
        "feature_lanes": [
            {"type": ftype, "features": features}
            for ftype, features in lanes.items()
            if features
        ],
        "features_raw": hp.features_raw or [],
    }


def build_human_xref_context(human_protein):
    grouped = {group: [] for group in XREF_GROUP_ORDER}
    for xref in human_protein.cross_references_raw or []:
        db = xref.get("database", "")
        group = _XREF_DB_TO_GROUP.get(db, "Other")
        grouped[group].append(xref)
    return {
        "groups": [
            {"label": group, "items": grouped[group]}
            for group in XREF_GROUP_ORDER
            if grouped[group]
        ],
    }

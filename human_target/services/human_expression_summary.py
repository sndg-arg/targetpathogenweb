"""Expression tab context for a human protein.

Buckets `HumanProtein.expression_json` (one row per (tissue, cell type) pair,
loaded from Bgee's expression-heatmap export -- see
`import_human_curated_proteins._load_expression`) into ~10 anatomical systems
for the "by system" view, and exposes a flat score-sorted list for the "by
rank" view (the view paginates that list, not this module). Bucketing is
deliberately done here at render time, not at ingest, so the keyword rules
can be retuned without re-ingesting.
"""

from __future__ import annotations

_SYSTEM_KEYWORDS = [
    (
        "Lymphoid & immune",
        (
            "lymph",
            "spleen",
            "thymus",
            "tonsil",
            "immune",
            "leukocyte",
            "bone marrow",
            "blood cell",
            "lymphocyte",
            "macrophage",
            "monocyte",
            "neutrophil",
        ),
    ),
    (
        "Digestive",
        (
            "intestine",
            "stomach",
            "esophagus",
            "liver",
            "pancrea",
            "colon",
            "rectum",
            "duoden",
            "salivary",
            "gallbladder",
            "gastric",
            "bowel",
        ),
    ),
    (
        "Reproductive",
        (
            "ovary",
            "ovarian",
            "testis",
            "testic",
            "uterus",
            "uterine",
            "prostate",
            "cervix",
            "vagina",
            "penis",
            "placenta",
            "endometri",
            "fallopian",
            "seminal",
            "mammary",
        ),
    ),
    (
        "Nervous",
        (
            "brain",
            "neuron",
            "spinal cord",
            "cortex",
            "cerebell",
            "hippocamp",
            "nerve",
            "retina",
            "thalamus",
            "hypothalamus",
            "glia",
            "cerebr",
        ),
    ),
    ("Endocrine", ("thyroid", "adrenal", "pituitary", "islet", "parathyroid", "hypophysis")),
    (
        "Cardiovascular",
        (
            "heart",
            "artery",
            "arter",
            "vein",
            "blood vessel",
            "cardiac",
            "atrium",
            "ventricle",
            "aorta",
            "myocard",
            "endothelial",
        ),
    ),
    ("Respiratory", ("lung", "bronch", "trachea", "alveol", "nasal", "pharynx", "larynx")),
    ("Urinary", ("kidney", "bladder", "ureter", "urethra", "renal", "metanephros", "nephron")),
    (
        "Musculoskeletal",
        ("muscle", "bone", "cartilage", "tendon", "ligament", "skeletal", "joint"),
    ),
    (
        "Integument & adipose",
        ("skin", "adipose", "fat pad", "epiderm", "dermis", "hair follicle", "sweat gland"),
    ),
]
_SYSTEM_ORDER = [system for system, _ in _SYSTEM_KEYWORDS] + ["Other"]


# Checked first: "cortex of kidney" must not fall into Nervous via "cortex".
_PRIORITY_SYSTEMS = ("Urinary",)


def _system_for_tissue(tissue):
    needle = (tissue or "").lower()
    ordered = sorted(_SYSTEM_KEYWORDS, key=lambda item: item[0] not in _PRIORITY_SYSTEMS)
    for system, keywords in ordered:
        if any(keyword in needle for keyword in keywords):
            return system
    return "Other"


# Bgee's expression score is 0-100; at or above this a tissue counts as one
# where the gene is clearly expressed (for the "expressed in N tissues" line).
EXPRESSED_SCORE = 50


def _is_gold(row):
    # The pilot export says "gold", Bgee's bulk file "gold quality".
    return str(row.get("quality") or "").strip().lower().startswith("gold")


def _is_absent(row):
    return str(row.get("state") or "").strip().lower() == "absent"


def tissue_specificity(scores):
    """Yanai et al.'s tau over per-tissue scores: 0 = same level everywhere,
    1 = expressed in a single tissue. None with fewer than two tissues."""
    scores = [max(0.0, float(score)) for score in scores]
    peak = max(scores, default=0.0)
    if len(scores) < 2 or peak <= 0:
        return None
    return sum(1 - score / peak for score in scores) / (len(scores) - 1)


def specificity_label(tau):
    if tau is None:
        return ""
    if tau >= 0.8:
        return "Tissue-specific"
    if tau >= 0.3:
        return "Intermediate specificity"
    return "Broadly expressed"


def build_human_expression_context(human_protein):
    rows = human_protein.expression_json or []
    ranked = sorted(rows, key=lambda row: row.get("score") or 0, reverse=True)
    present = [row for row in ranked if not _is_absent(row)]

    # One score per tissue (its best cell type / call), for tau and breadth.
    by_tissue = {}
    for row in present:
        tissue = (row.get("tissue") or row.get("cell_type") or "").strip()
        if tissue:
            by_tissue[tissue] = max(by_tissue.get(tissue, 0.0), float(row.get("score") or 0))
    tau = tissue_specificity(by_tissue.values())

    by_system = {}
    for row in ranked:
        system = _system_for_tissue(row.get("tissue"))
        by_system.setdefault(system, []).append(row)
    system_groups = []
    for system in _SYSTEM_ORDER:
        if system not in by_system:
            continue
        group_rows = by_system[system]
        top = next((row for row in group_rows if not _is_absent(row)), None)
        system_groups.append(
            {
                "system": system,
                "slug": system.lower().replace(" & ", "-").replace(" ", "-"),
                "rows": group_rows,
                "top": top,
                "max_score": (top or {}).get("score") or 0,
            }
        )
    peak = present[0] if present else None

    return {
        "has_expression": bool(rows),
        "total_count": len(rows),
        "gold_count": sum(1 for row in rows if _is_gold(row)),
        "peak": peak,
        "peak_is_gold": bool(peak and _is_gold(peak)),
        "tissue_count": len(by_tissue),
        "expressed_count": sum(1 for score in by_tissue.values() if score >= EXPRESSED_SCORE),
        "expressed_threshold": EXPRESSED_SCORE,
        "tau": tau,
        "specificity_label": specificity_label(tau),
        "system_groups": system_groups,
        "ranked": ranked,
    }

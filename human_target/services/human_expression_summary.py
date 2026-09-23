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
    ("Urinary", ("kidney", "bladder", "ureter", "urethra", "renal")),
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


def _system_for_tissue(tissue):
    needle = (tissue or "").lower()
    for system, keywords in _SYSTEM_KEYWORDS:
        if any(keyword in needle for keyword in keywords):
            return system
    return "Other"


def build_human_expression_context(human_protein):
    rows = human_protein.expression_json or []
    ranked = sorted(rows, key=lambda row: row.get("score") or 0, reverse=True)

    by_system = {}
    for row in ranked:
        system = _system_for_tissue(row.get("tissue"))
        by_system.setdefault(system, []).append(row)
    system_groups = [
        {"system": system, "rows": by_system[system]}
        for system in _SYSTEM_ORDER
        if system in by_system
    ]

    return {
        "has_expression": bool(rows),
        "total_count": len(rows),
        "gold_count": sum(1 for row in rows if row.get("quality") == "gold"),
        "peak": ranked[0] if ranked else None,
        "system_groups": system_groups,
        "ranked": ranked,
    }

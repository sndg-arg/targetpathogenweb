"""Proteome-wide ligand coverage for reviewed human proteins (the Ligand
Coverage Atlas page), plus the cheap headline counts the protein list shows.

The atlas aggregates ~1M `Binders` rows, so it is cached and warmed by
`refresh_human_target_summary`; the list headline reads the stored
per-protein summary fields instead.
"""

from __future__ import annotations

from django.core.cache import cache
from django.db.models import Count, Q, Sum

from tpweb.models.Binders import Binders

from .human_targets import HUMAN_BIODATABASE_NAME, human_proteins_queryset

ATLAS_CACHE_KEY = "Target:human_ligand_atlas:v1"
ATLAS_CACHE_TTL_SECONDS = 86400

_SEQUENCE = Q(notes__startswith="LigQ sequence")
_PDB = Q(source=Binders.SOURCE_PDB)
_CHEMBL = Q(source=Binders.SOURCE_CHEMBL)
_DIRECT = Q(is_direct=True)

# (key, tier, label, filter): mutually exclusive, strongest evidence first.
CATEGORIES = [
    ("direct_pdb", "This protein", "Co-crystal structure (PDB)", _PDB & _DIRECT),
    ("direct_chembl", "This protein", "Measured activity (ChEMBL)", _CHEMBL & _DIRECT),
    ("homolog_pdb", "Homolog", "Co-crystal structure (PDB)", _PDB & ~_DIRECT & _SEQUENCE),
    ("homolog_chembl", "Homolog", "Measured activity (ChEMBL)", _CHEMBL & ~_DIRECT & _SEQUENCE),
    (
        "domain_pdb",
        "Shared Pfam domain",
        "Co-crystal structure (PDB)",
        _PDB & ~_DIRECT & ~_SEQUENCE,
    ),
    (
        "domain_chembl",
        "Shared Pfam domain",
        "Measured activity (ChEMBL)",
        _CHEMBL & ~_DIRECT & ~_SEQUENCE,
    ),
    ("zinc", "Chemical similarity", "Proposed compound (ZINC)", Q(source=Binders.SOURCE_PROPOSED)),
]
KNOWN_KEYS = [key for key, *_ in CATEGORIES if key != "zinc"]

# Strongest evidence per protein: (label, category keys that qualify).
LADDER = [
    ("Co-crystallized with this protein", ["direct_pdb"]),
    ("Activity measured on this protein", ["direct_chembl"]),
    ("Transferred from a homolog", ["homolog_pdb", "homolog_chembl"]),
    ("Transferred via a shared Pfam domain", ["domain_pdb", "domain_chembl"]),
    ("Proposed by chemical similarity only", ["zinc"]),
]

# (label, potency hint, low, high): pChEMBL = -log10(molar IC50/Ki/...).
PCHEMBL_BINS = [
    ("< 5", "> 10 µM", None, 5),
    ("5–6", "~10 µM", 5, 6),
    ("6–7", "~1 µM", 6, 7),
    ("7–8", "~100 nM", 7, 8),
    ("8–9", "~10 nM", 8, 9),
    ("9–10", "~1 nM", 9, 10),
    ("≥ 10", "< 1 nM", 10, None),
]

# (label, low, high) known ligands (PDB + ChEMBL) per protein.
RICHNESS_BINS = [
    ("1", 1, 1),
    ("2–5", 2, 5),
    ("6–10", 6, 10),
    ("11–25", 11, 25),
    ("26–50", 26, 50),
    ("51–100", 51, 100),
    ("> 100", 101, None),
]


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else 0


def _with_bars(rows, total=None):
    """Adds pct (of total, default the largest count) for bar widths."""
    scale = total or max((row["count"] for row in rows), default=0)
    for row in rows:
        row["pct"] = _pct(row["count"], scale)
    return rows


def _in_range(value, low, high):
    return (low is None or value >= low) and (high is None or value <= high)


def human_list_headline():
    """Counts for the protein list hero, from stored summary fields."""
    return human_proteins_queryset().aggregate(
        total_proteins=Count("pk"),
        proteins_with_ligands=Count("pk", filter=Q(ligand_count__gt=0)),
        total_ligand_records=Sum("ligand_count", default=0),
    )


def build_ligand_atlas_context(refresh=False):
    if not refresh:
        cached = cache.get(ATLAS_CACHE_KEY)
        if cached is not None:
            return cached
    context = _compute_atlas()
    cache.set(ATLAS_CACHE_KEY, context, ATLAS_CACHE_TTL_SECONDS)
    return context


def _compute_atlas():
    proteins = dict(
        human_proteins_queryset()
        .filter(is_reviewed=True)
        .values_list("uniprot_accession", "experimental_structure_count")
    )
    total = len(proteins)

    binders = Binders.objects.filter(
        locustag__biodatabase__name=HUMAN_BIODATABASE_NAME,
        locustag__human_protein__is_reviewed=True,
    )
    per_protein = list(
        binders.values("locustag_id").annotate(
            **{key: Count("id", filter=condition) for key, _t, _l, condition in CATEGORIES}
        )
    )

    categories = _with_bars(
        [
            {
                "key": key,
                "tier": tier,
                "label": label,
                "count": sum(1 for row in per_protein if row[key]),
                "records": sum(row[key] for row in per_protein),
            }
            for key, tier, label, _condition in CATEGORIES
        ],
        total,
    )

    ladder = []
    remaining = per_protein
    for label, keys in LADDER:
        hit = [row for row in remaining if any(row[key] for key in keys)]
        remaining = [row for row in remaining if not any(row[key] for key in keys)]
        ladder.append({"label": label, "count": len(hit)})
    with_ligands = sum(row["count"] for row in ladder)
    ladder.append({"label": "No ligand evidence", "count": total - with_ligands, "is_none": True})
    _with_bars(ladder, total)

    known_counts = [sum(row[key] for key in KNOWN_KEYS) for row in per_protein]
    known_counts = [n for n in known_counts if n]
    richness = _with_bars(
        [
            {"label": label, "count": sum(1 for n in known_counts if _in_range(n, low, high))}
            for label, low, high in RICHNESS_BINS
        ]
    )

    chembl_scores = binders.filter(_CHEMBL, score__isnull=False)
    bin_filters = {}
    for index, (_label, _hint, low, high) in enumerate(PCHEMBL_BINS):
        condition = Q()
        if low is not None:
            condition &= Q(score__gte=low)
        if high is not None:
            condition &= Q(score__lt=high)
        bin_filters[f"bin{index}"] = Count("id", filter=condition)
    bin_counts = chembl_scores.aggregate(**bin_filters)
    potency = _with_bars(
        [
            {"label": label, "hint": hint, "count": bin_counts[f"bin{index}"] or 0}
            for index, (label, hint, _low, _high) in enumerate(PCHEMBL_BINS)
        ]
    )

    liganded = {row["locustag_id"] for row in per_protein}
    known = {row["locustag_id"] for row in per_protein if any(row[k] for k in KNOWN_KEYS)}
    with_structure = {acc for acc, n in proteins.items() if n}
    structure_matrix = [
        {"label": "Known ligands and a PDB structure", "count": len(known & with_structure)},
        {"label": "Known ligands, predicted structure only", "count": len(known - with_structure)},
        {"label": "PDB structure, no known ligands", "count": len(with_structure - known)},
        {
            "label": "Neither",
            "count": total - len(known | with_structure),
        },
    ]
    _with_bars(structure_matrix, total)

    direct = sum(1 for row in per_protein if row["direct_pdb"] or row["direct_chembl"])
    return {
        "total_proteins": total,
        "proteins_with_ligands": len(liganded),
        "proteins_with_ligands_pct": _pct(len(liganded), total),
        "proteins_with_known": len(known),
        "proteins_direct": direct,
        "proteins_direct_pct": _pct(direct, total),
        "proteins_cocrystal": categories[0]["count"],
        "total_ligand_records": sum(row["records"] for row in categories),
        "chembl_scored": sum(row["count"] for row in potency),
        "ladder": ladder,
        "categories": categories,
        "potency": potency,
        "richness": richness,
        "structure_matrix": structure_matrix,
    }

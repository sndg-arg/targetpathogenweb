"""Proteome-wide dashboard context for the Human Targets list page.

Real aggregation queries over `Binders` scoped to the curated human
`Biodatabase`, not a stored/precomputed blob -- at pilot scale (10 curated
proteins) these numbers are necessarily sparse compared to what a full
~20,400-protein proteome run would show; the template surfaces that as an
explicit caveat rather than trying to make 10 proteins "look like" proteome
scale.
"""

from __future__ import annotations

from django.db.models import Count, Q

from tpweb.models.Binders import Binders

from .human_targets import human_bioentries_queryset

_PCHEMBL_BINS = [
    ("< 4", Q(score__lt=4)),
    ("4 – 6", Q(score__gte=4, score__lt=6)),
    ("6 – 8", Q(score__gte=6, score__lt=8)),
    ("8 – 10", Q(score__gte=8, score__lt=10)),
    ("≥ 10", Q(score__gte=10)),
]

# (label, low, high) -- high=None means "and above".
_RICHNESS_BINS = [
    ("1", 1, 1),
    ("2–5", 2, 5),
    ("6–10", 6, 10),
    ("11–20", 11, 20),
    ("21+", 21, None),
]


def build_human_dashboard_context():
    bioentries = human_bioentries_queryset()
    total_proteins = bioentries.count()

    binders = Binders.objects.filter(locustag__in=bioentries)
    total_ligand_records = binders.count()

    by_source = binders.aggregate(
        pdb=Count("id", filter=Q(source=Binders.SOURCE_PDB)),
        chembl=Count("id", filter=Q(source=Binders.SOURCE_CHEMBL)),
        zinc=Count("id", filter=Q(source=Binders.SOURCE_PROPOSED)),
    )
    by_evidence = binders.aggregate(
        direct=Count("id", filter=Q(is_direct=True)),
        homolog=Count("id", filter=Q(is_direct=False)),
    )

    chembl_binders = binders.filter(source=Binders.SOURCE_CHEMBL, score__isnull=False)
    pchembl_bins = [
        {"label": label, "count": chembl_binders.filter(query).count()}
        for label, query in _PCHEMBL_BINS
    ]

    counts_per_protein = list(
        binders.values("locustag").annotate(n=Count("id")).values_list("n", flat=True)
    )
    richness_bins = []
    for label, low, high in _RICHNESS_BINS:
        if high is None:
            count = sum(1 for n in counts_per_protein if n >= low)
        else:
            count = sum(1 for n in counts_per_protein if low <= n <= high)
        richness_bins.append({"label": label, "count": count})

    proteins_with_ligands = len(counts_per_protein)

    return {
        "total_proteins": total_proteins,
        "total_ligand_records": total_ligand_records,
        "proteins_with_ligands": proteins_with_ligands,
        "proteins_without_ligands": max(0, total_proteins - proteins_with_ligands),
        "by_source": by_source,
        "by_evidence": by_evidence,
        "pchembl_bins": pchembl_bins,
        "richness_bins": richness_bins,
    }

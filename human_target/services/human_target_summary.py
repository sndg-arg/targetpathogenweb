"""Per-protein evidence summary behind the Human Targets list columns, filters
and sorting: counts and labels computed once from what is already loaded
(UniProt fields, structures, ligands, pathways, expression) and stored on
HumanProtein, so the list can filter and sort ~20,000 proteins in SQL.
"""

from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from human_target.services.human_dossier import compartments_for
from human_target.services.human_expression_summary import tissue_specificity

SUMMARY_FIELDS = [
    "structure_count",
    "experimental_structure_count",
    "ligand_count",
    "direct_ligand_count",
    "drugbank_count",
    "disease_count",
    "pathway_count",
    "tissue_specificity",
    "peak_tissue",
    "surface_accessible",
    "summary_updated_at",
]
_SURFACE = {"membrane", "secreted"}


def _expression_summary(rows):
    """(tau, peak tissue) from the expressed (not 'absent') Bgee calls."""
    by_tissue = {}
    for row in rows or []:
        if str(row.get("state") or "").strip().lower() == "absent":
            continue
        tissue = (row.get("tissue") or row.get("cell_type") or "").strip()
        if tissue:
            by_tissue[tissue] = max(by_tissue.get(tissue, 0.0), float(row.get("score") or 0))
    if not by_tissue:
        return None, ""
    peak = max(by_tissue, key=by_tissue.get)
    tau = tissue_specificity(by_tissue.values())
    return (round(tau, 3) if tau is not None else None), peak[:255]


def summarize(protein, structures, ligands, pathways):
    """Fill the summary fields of one HumanProtein (not saved)."""
    total, experimental = structures.get(protein.bioentry_id, (0, 0))
    ligand_total, ligand_direct = ligands.get(protein.bioentry_id, (0, 0))
    protein.structure_count = total
    protein.experimental_structure_count = experimental
    protein.ligand_count = ligand_total
    protein.direct_ligand_count = ligand_direct
    protein.drugbank_count = len(
        {
            xref.get("id")
            for xref in protein.cross_references_raw or []
            if xref.get("database") == "DrugBank"
        }
    )
    protein.disease_count = len(protein.disease_comments or [])
    protein.pathway_count = pathways.get(protein.pk, 0)
    protein.tissue_specificity, protein.peak_tissue = _expression_summary(protein.expression_json)
    protein.surface_accessible = bool(
        _SURFACE.intersection(compartments_for(protein.subcellular_locations))
    )
    protein.summary_updated_at = timezone.now()
    return protein


def refresh_summaries(queryset, batch_size=500, stdout=None):
    """Recompute the summary for every protein in `queryset`; returns the count."""
    from human_target.models.HumanProteinPathway import HumanProteinPathway
    from tpweb.models.Binders import Binders
    from tpweb.models.BioentryStructure import BioentryStructure

    # The full UniProt record is the heaviest column and is not needed here.
    queryset = queryset.defer("uniprot_raw", "features_raw", "publications", "sequence").order_by(
        "pk"
    )
    done = 0
    batch = []
    for protein in queryset.iterator(chunk_size=batch_size):
        batch.append(protein)
        if len(batch) >= batch_size:
            done += _refresh_batch(batch, BioentryStructure, Binders, HumanProteinPathway)
            batch = []
            if stdout:
                stdout.write(f"  {done} proteins summarized")
    if batch:
        done += _refresh_batch(batch, BioentryStructure, Binders, HumanProteinPathway)
    return done


def _refresh_batch(batch, BioentryStructure, Binders, HumanProteinPathway):
    from human_target.models.HumanProtein import HumanProtein

    bioentry_ids = [p.bioentry_id for p in batch]
    structures = {
        row["bioentry_id"]: (row["total"], row["experimental"])
        for row in BioentryStructure.objects.filter(bioentry_id__in=bioentry_ids)
        .values("bioentry_id")
        .annotate(total=Count("id"), experimental=Count("id", filter=Q(pdb__experiment="EX")))
    }
    ligands = {
        row["locustag__bioentry_id"]: (row["total"], row["direct"])
        for row in Binders.objects.filter(locustag__bioentry_id__in=bioentry_ids)
        .values("locustag__bioentry_id")
        .annotate(total=Count("id"), direct=Count("id", filter=Q(is_direct=True)))
    }
    pathways = {
        row["human_protein_id"]: row["total"]
        for row in HumanProteinPathway.objects.filter(human_protein_id__in=[p.pk for p in batch])
        .values("human_protein_id")
        .annotate(total=Count("id"))
    }
    for protein in batch:
        summarize(protein, structures, ligands, pathways)
    HumanProtein.objects.bulk_update(batch, SUMMARY_FIELDS, batch_size=500)
    return len(batch)

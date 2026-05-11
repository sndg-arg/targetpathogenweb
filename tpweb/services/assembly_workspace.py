from django.db.models import Count, Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.Binders import Binders
from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)


EC_DBNAMES = {str(Ontology.EC or "").strip(), "ec", "EC"}


def _pct(numerator, denominator):
    if not denominator:
        return 0
    return round(100 * numerator / denominator, 1)


def get_top_targets_by_binders(assembly_name, limit=5):
    """Return the top-N proteins of a genome ranked by total binder count.

    Used to surface the most actionable drug-target leads on the genome overview.
    """
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    rows = (
        Binders.objects.filter(locustag__biodatabase__name=proteome_name)
        .values(
            "locustag__bioentry_id",
            "locustag__accession",
            "locustag__description",
        )
        .annotate(
            binder_count=Count("id"),
            pdb_count=Count("id", filter=Q(source=Binders.SOURCE_PDB)),
            chembl_count=Count("id", filter=Q(source=Binders.SOURCE_CHEMBL)),
            zinc_count=Count("id", filter=Q(source=Binders.SOURCE_PROPOSED)),
        )
        .order_by("-binder_count")[:limit]
    )
    return [
        {
            "bioentry_id": r["locustag__bioentry_id"],
            "accession": r["locustag__accession"],
            "description": r["locustag__description"],
            "binder_count": r["binder_count"],
            "pdb_count": r["pdb_count"],
            "chembl_count": r["chembl_count"],
            "zinc_count": r["zinc_count"],
        }
        for r in rows
    ]


def build_assembly_workspace_metrics(assembly_name):
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    proteins = Bioentry.objects.filter(biodatabase__name=proteome_name)

    total_proteins = proteins.count()
    proteins_with_structure = proteins.filter(structures__isnull=False).distinct().count()
    experimental_structures = (
        BioentryStructure.objects.filter(bioentry__biodatabase__name=proteome_name)
        .exclude(pdb__experiment__in=PDB_MODEL_EXPERIMENTS)
        .values("bioentry_id")
        .distinct()
        .count()
    )
    alphafold_structures = (
        proteins.filter(structures__pdb__experiment=PDB_EXPERIMENT_ALPHAFOLD).distinct().count()
    )
    colabfold_structures = (
        proteins.filter(structures__pdb__experiment=PDB_EXPERIMENT_COLABFOLD).distinct().count()
    )
    ec_annotated = proteins.filter(dbxrefs__dbxref__dbname__in=EC_DBNAMES).distinct().count()
    go_annotated = proteins.filter(dbxrefs__dbxref__dbname=Ontology.GO).distinct().count()
    functional_annotated = proteins.filter(
        Q(dbxrefs__dbxref__dbname__in=EC_DBNAMES) | Q(dbxrefs__dbxref__dbname=Ontology.GO)
    ).distinct().count()

    binders_qs = Binders.objects.filter(locustag__biodatabase__name=proteome_name)
    binder_total = binders_qs.count()
    binder_pdb = binders_qs.filter(source=Binders.SOURCE_PDB).count()
    binder_chembl = binders_qs.filter(source=Binders.SOURCE_CHEMBL).count()
    binder_zinc = binders_qs.filter(source=Binders.SOURCE_PROPOSED).count()
    proteins_with_binders = (
        binders_qs.values("locustag_id").distinct().count() if binder_total else 0
    )

    return {
        "total_proteins": total_proteins,
        "proteins_with_structure": proteins_with_structure,
        "structure_coverage_pct": _pct(proteins_with_structure, total_proteins),
        "experimental_structures": experimental_structures,
        "alphafold_structures": alphafold_structures,
        "colabfold_structures": colabfold_structures,
        "functional_annotated": functional_annotated,
        "functional_coverage_pct": _pct(functional_annotated, total_proteins),
        "ec_annotated": ec_annotated,
        "ec_coverage_pct": _pct(ec_annotated, total_proteins),
        "go_annotated": go_annotated,
        "go_coverage_pct": _pct(go_annotated, total_proteins),
        "binder_total": binder_total,
        "binder_pdb": binder_pdb,
        "binder_chembl": binder_chembl,
        "binder_zinc": binder_zinc,
        "proteins_with_binders": proteins_with_binders,
        "binder_coverage_pct": _pct(proteins_with_binders, total_proteins),
    }

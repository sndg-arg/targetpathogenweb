from django.db.models import Count, Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
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
    """Top-N proteins of a genome ranked by total binder count.

    This is "most-studied" evidence, NOT a drug-target ranking — proteins with
    well-studied human homologs (kinases, GPCRs) accumulate many ChEMBL/ZINC
    hits regardless of whether they are good bacterial targets. Use as a
    "ligand evidence" view, not a target prioritization.
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
            direct_count=Count("id", filter=Q(source__in=[Binders.SOURCE_PDB, Binders.SOURCE_CHEMBL], is_direct=True)),
            homolog_count=Count("id", filter=Q(source__in=[Binders.SOURCE_PDB, Binders.SOURCE_CHEMBL], is_direct=False)),
            pdb_count=Count("id", filter=Q(source=Binders.SOURCE_PDB)),
            pdb_direct_count=Count("id", filter=Q(source=Binders.SOURCE_PDB, is_direct=True)),
            pdb_homolog_count=Count("id", filter=Q(source=Binders.SOURCE_PDB, is_direct=False)),
            chembl_count=Count("id", filter=Q(source=Binders.SOURCE_CHEMBL)),
            chembl_direct_count=Count("id", filter=Q(source=Binders.SOURCE_CHEMBL, is_direct=True)),
            chembl_homolog_count=Count("id", filter=Q(source=Binders.SOURCE_CHEMBL, is_direct=False)),
            zinc_count=Count("id", filter=Q(source=Binders.SOURCE_PROPOSED)),
        )
        .order_by("-direct_count", "-binder_count")[:limit]
    )
    return [
        {
            "bioentry_id": r["locustag__bioentry_id"],
            "accession": r["locustag__accession"],
            "description": r["locustag__description"],
            "binder_count": r["binder_count"],
            "direct_count": r["direct_count"],
            "homolog_count": r["homolog_count"],
            "pdb_count": r["pdb_count"],
            "pdb_direct_count": r["pdb_direct_count"],
            "pdb_homolog_count": r["pdb_homolog_count"],
            "chembl_count": r["chembl_count"],
            "chembl_direct_count": r["chembl_direct_count"],
            "chembl_homolog_count": r["chembl_homolog_count"],
            "zinc_count": r["zinc_count"],
        }
        for r in rows
    ]


_FACTOR_LABELS = {
    # Map score_param values → biologist-friendly chip labels.
    # First match wins; covers the canonical pipeline params.
    "essenciality": {
        "Y": ("Essential", "good"),
        "N": ("Non-essential", "neutral"),
    },
    "essentiality": {
        "Y": ("Essential", "good"),
        "N": ("Non-essential", "neutral"),
    },
    "human_offtarget": {
        "N": ("No human off-target", "good"),
        "Y": ("Has human off-target", "bad"),
    },
    "micro_offtarget": {
        "N": ("No microbiome off-target", "good"),
        "Y": ("Has microbiome off-target", "bad"),
    },
    "druggability": {
        "Y": ("Druggable pocket", "good"),
        "N": ("No druggable pocket", "neutral"),
        "High": ("Highly druggable pocket", "good"),
        "H": ("Highly druggable pocket", "good"),
        "Medium": ("Moderately druggable", "neutral"),
        "M": ("Moderately druggable", "neutral"),
        "Low": ("Low druggability", "bad"),
        "L": ("Low druggability", "bad"),
    },
    "psort": {
        "Y": ("Surface-exposed", "good"),
    },
}


def _humanize_factor(param_name, value):
    spec = _FACTOR_LABELS.get(param_name.lower())
    if not spec:
        return None
    result = spec.get(str(value))
    if result:
        return result
    # Numeric druggability: apply FPocket thresholds (≥0.7 high, ≥0.4 medium)
    if param_name.lower() == "druggability":
        try:
            v = float(value)
            fmt = f"{v:.3f}".rstrip("0").rstrip(".")
            if v >= 0.7:
                return (f"Highly druggable · {fmt}", "good")
            elif v >= 0.4:
                return (f"Moderately druggable · {fmt}", "neutral")
            elif v > 0:
                return (f"Low druggability · {fmt}", "bad")
            else:
                return ("No druggable pocket", "neutral")
        except (ValueError, TypeError):
            pass
    return None


def get_top_targets_by_score(assembly_name, user, limit=5):
    """Top-N proteins of a genome ranked by raw FPocket druggability.

    The genome overview should show an interpretable single-evidence ranking by
    default. Composite formulas belong in the protein list scoring drawer.
    """
    from tpweb.services.protein_serializer import score_param_value_map

    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    proteins = (
        Bioentry.objects.filter(biodatabase__name=proteome_name)
        .prefetch_related("score_params__score_param")
    )

    binder_counts_by_source = {}
    for row in (
        Binders.objects.filter(locustag__biodatabase__name=proteome_name)
        .values("locustag__accession", "source")
        .annotate(count=Count("id"))
    ):
        acc = row["locustag__accession"]
        binder_counts_by_source.setdefault(acc, {})[row["source"]] = row["count"]

    scored = []
    for p in proteins:
        param_values = score_param_value_map(p)
        raw_druggability = param_values.get("Druggability")
        try:
            score = float(raw_druggability or 0)
        except (TypeError, ValueError):
            score = 0.0
        counts = binder_counts_by_source.get(p.accession, {})
        pdb_c = counts.get(Binders.SOURCE_PDB, 0)
        chembl_c = counts.get(Binders.SOURCE_CHEMBL, 0)
        zinc_c = counts.get(Binders.SOURCE_PROPOSED, 0)
        binder_count = pdb_c + chembl_c + zinc_c
        scored.append((p, score, param_values, binder_count, pdb_c, chembl_c, zinc_c))

    # Sort by druggability, breaking ties by binder count so well-evidenced proteins surface first.
    scored.sort(key=lambda row: (row[1], row[3]), reverse=True)
    top = scored[:limit]

    items = []
    for p, score, param_values, binder_count, pdb_c, chembl_c, zinc_c in top:
        factors = []
        label_spec = _humanize_factor("Druggability", score)
        if label_spec:
            label, tone = label_spec
            factors.append({"label": label, "tone": tone})
        items.append({
            "bioentry_id": p.bioentry_id,
            "accession": p.accession,
            "description": p.description,
            "score": round(score, 2),
            "factors": factors,
            "binder_count": binder_count,
            "pdb_count": pdb_c,
            "chembl_count": chembl_c,
            "zinc_count": zinc_c,
        })

    return {"formula_name": "Druggability", "items": items}


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
    experimental_structure_xrefs = ExperimentalStructureXref.objects.filter(
        bioentry__biodatabase__name=proteome_name,
    )
    pdb_xref_entries = experimental_structure_xrefs.count()
    pdb_xref_proteins = experimental_structure_xrefs.values("bioentry_id").distinct().count()
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
    binder_pdb_direct = binders_qs.filter(source=Binders.SOURCE_PDB, is_direct=True).count()
    binder_pdb_homolog = binders_qs.filter(source=Binders.SOURCE_PDB, is_direct=False).count()
    binder_chembl_direct = binders_qs.filter(source=Binders.SOURCE_CHEMBL, is_direct=True).count()
    binder_chembl_homolog = binders_qs.filter(source=Binders.SOURCE_CHEMBL, is_direct=False).count()
    binder_zinc = binders_qs.filter(source=Binders.SOURCE_PROPOSED).count()
    binder_direct = binder_pdb_direct + binder_chembl_direct
    binder_homolog = binder_pdb_homolog + binder_chembl_homolog
    proteins_with_binders = (
        binders_qs.values("locustag_id").distinct().count() if binder_total else 0
    )

    return {
        "total_proteins": total_proteins,
        "proteins_with_structure": proteins_with_structure,
        "structure_coverage_pct": _pct(proteins_with_structure, total_proteins),
        "experimental_structures": experimental_structures,
        "pdb_xref_entries": pdb_xref_entries,
        "pdb_xref_proteins": pdb_xref_proteins,
        "alphafold_structures": alphafold_structures,
        "colabfold_structures": colabfold_structures,
        "functional_annotated": functional_annotated,
        "functional_coverage_pct": _pct(functional_annotated, total_proteins),
        "ec_annotated": ec_annotated,
        "ec_coverage_pct": _pct(ec_annotated, total_proteins),
        "go_annotated": go_annotated,
        "go_coverage_pct": _pct(go_annotated, total_proteins),
        "binder_total": binder_total,
        "binder_pdb_direct": binder_pdb_direct,
        "binder_pdb_homolog": binder_pdb_homolog,
        "binder_chembl_direct": binder_chembl_direct,
        "binder_chembl_homolog": binder_chembl_homolog,
        "binder_zinc": binder_zinc,
        "binder_direct": binder_direct,
        "binder_homolog": binder_homolog,
        # legacy keys kept for backward compat
        "binder_pdb": binder_pdb_direct + binder_pdb_homolog,
        "binder_chembl": binder_chembl_direct + binder_chembl_homolog,
        "proteins_with_binders": proteins_with_binders,
        "binder_coverage_pct": _pct(proteins_with_binders, total_proteins),
    }

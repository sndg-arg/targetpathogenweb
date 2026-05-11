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
    },
    "psort": {
        "Y": ("Surface-exposed", "good"),
    },
}


def _humanize_factor(param_name, value):
    spec = _FACTOR_LABELS.get(param_name.lower())
    if not spec:
        return None
    return spec.get(value)


def get_top_targets_by_score(assembly_name, user, limit=5):
    """Top-N proteins of a genome ranked by the user's default scoring formula.

    Returns each target with the top 3 contributing factors (chips), so a
    biologist sees *why* a target ranks high (Essential, no human off-target,
    druggable pocket…) without clicking through.
    """
    from tpweb.services.protein_formula import (
        choose_formula,
        coefficient_map,
        resolve_formulas_for_user,
    )
    from tpweb.services.protein_serializer import (
        compute_score_value,
        score_param_value_map,
    )

    formulas = resolve_formulas_for_user(user)
    if not formulas:
        return {"formula_name": None, "items": []}
    formula = choose_formula(formulas, None)
    if not formula:
        return {"formula_name": None, "items": []}

    formula_terms = list(formula.terms.all())
    coef = coefficient_map(formula_terms)

    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    proteins = (
        Bioentry.objects.filter(biodatabase__name=proteome_name)
        .prefetch_related("score_params__score_param")
    )

    scored = []
    for p in proteins:
        param_values = score_param_value_map(p)
        score, weights = compute_score_value(param_values, coef)
        scored.append((p, score, weights, param_values))

    scored.sort(key=lambda row: row[1], reverse=True)
    top = scored[:limit]

    items = []
    for p, score, weights, param_values in top:
        # Top 3 contributing params by absolute coefficient
        ranked_params = sorted(weights.items(), key=lambda kv: abs(kv[1]), reverse=True)[:4]
        factors = []
        for param_name, contribution in ranked_params:
            value = param_values.get(param_name)
            label_spec = _humanize_factor(param_name, str(value))
            if label_spec:
                label, tone = label_spec
                factors.append({"label": label, "tone": tone})
            else:
                # Generic chip if no friendly mapping exists
                factors.append({
                    "label": f"{param_name}: {value}",
                    "tone": "good" if contribution > 0 else "neutral",
                })
        items.append({
            "bioentry_id": p.bioentry_id,
            "accession": p.accession,
            "description": p.description,
            "score": round(score, 2),
            "factors": factors,
        })

    return {"formula_name": formula.name, "items": items}


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

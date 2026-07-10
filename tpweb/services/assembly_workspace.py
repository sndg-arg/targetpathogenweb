from django.db.models import Count, Q

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
from tpweb.models.Binders import Binders
from tpweb.models.Metabolism import GeneReactionLink, MetabolicReaction
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.structure_sources import (
    PDB_EXPERIMENT_ALPHAFOLD,
    PDB_EXPERIMENT_COLABFOLD,
    PDB_MODEL_EXPERIMENTS,
)


EC_DBNAMES = {str(Ontology.EC or "").strip(), "ec", "EC"}
EVIDENCE_CONVERGENCE_MAX_SCORE = 15.0


def _pct(numerator, denominator):
    if not denominator:
        return 0
    return round(100 * numerator / denominator, 1)


def _format_decimal(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _evidence_convergence_tier(score):
    fraction = score / EVIDENCE_CONVERGENCE_MAX_SCORE
    if fraction >= 0.65:
        return "Strong", "good"
    if fraction >= 0.4:
        return "Moderate", "neutral"
    return "Limited", "bad"


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


def _as_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _is_yes(value):
    return str(value or "").strip().lower() in {"y", "yes", "true", "1"}


def _is_no_hit(value):
    return str(value or "").strip().lower().replace(" ", "_") in {"no_hit", "nohit"}


def _is_core_call(value):
    return str(value or "").strip().lower() in {"core", "y", "yes", "true", "1"}


def _add_signal(signals, label, tone="good"):
    if label and all(existing["label"] != label for existing in signals):
        signals.append({"label": label, "tone": tone})


def _score_proteins(assembly_name):
    """Compute the evidence-convergence score for every scoreable protein in a genome.

    Shared by get_top_targets_by_score (ranked overall) and
    get_unexplored_targets (ranked among proteins with zero ligand evidence).
    Returned rows are plain dicts, unsorted.
    """
    from tpweb.services.protein_serializer import score_param_value_map

    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    proteins = (
        Bioentry.objects.filter(biodatabase__name=proteome_name)
        .prefetch_related("score_params__score_param")
    )

    binder_counts_by_gene = {}
    for row in (
        Binders.objects.filter(locustag__biodatabase__name=proteome_name)
        .values("locustag__bioentry_id", "source", "is_direct")
        .annotate(count=Count("id"))
    ):
        gene_id = row["locustag__bioentry_id"]
        source = row["source"]
        direct_key = "direct" if row["is_direct"] else "homolog"
        counts = binder_counts_by_gene.setdefault(gene_id, {
            "pdb_direct": 0,
            "pdb_homolog": 0,
            "chembl_direct": 0,
            "chembl_homolog": 0,
            "zinc": 0,
        })
        if source == Binders.SOURCE_PDB:
            counts[f"pdb_{direct_key}"] += row["count"]
        elif source == Binders.SOURCE_CHEMBL:
            counts[f"chembl_{direct_key}"] += row["count"]
        elif source == Binders.SOURCE_PROPOSED:
            counts["zinc"] += row["count"]

    structure_rows = BioentryStructure.objects.filter(
        bioentry__biodatabase__name=proteome_name,
    ).values("bioentry_id", "pdb__experiment")
    proteins_with_structure = set()
    proteins_with_experimental_structure = set()
    for row in structure_rows:
        gene_id = row["bioentry_id"]
        proteins_with_structure.add(gene_id)
        if (row["pdb__experiment"] or "") not in PDB_MODEL_EXPERIMENTS:
            proteins_with_experimental_structure.add(gene_id)

    metabolic_links = GeneReactionLink.objects.filter(
        reaction__genome_accession=assembly_name,
    ).values("bioentry_id", "chokepoint_role")
    metabolic_gene_ids = set()
    chokepoint_gene_ids = set()
    for row in metabolic_links:
        gene_id = row["bioentry_id"]
        metabolic_gene_ids.add(gene_id)
        if row["chokepoint_role"] != GeneReactionLink.CHOKEPOINT_NONE:
            chokepoint_gene_ids.add(gene_id)

    scored = []
    for p in proteins:
        param_values = score_param_value_map(p)
        gene_id = p.bioentry_id
        signals = []
        cautions = []
        score = 0.0

        fpocket = _as_float(param_values.get("Druggability"))
        if fpocket is not None:
            if fpocket >= 0.7:
                score += 2.0
                _add_signal(signals, f"High FPocket druggability {_format_decimal(fpocket)}")
            elif fpocket >= 0.4:
                score += 1.0
                _add_signal(signals, f"Moderate FPocket druggability {_format_decimal(fpocket)}", "neutral")
            elif fpocket > 0:
                score -= 0.5
                _add_signal(cautions, f"Weak FPocket druggability {_format_decimal(fpocket)}", "bad")

        p2rank = _as_float(param_values.get("p2rank_probability"))
        if p2rank is not None and p2rank >= 0.5:
            score += 1.0
            _add_signal(signals, "P2Rank pocket support")

        binder_counts = binder_counts_by_gene.get(gene_id, {})
        pdb_direct = binder_counts.get("pdb_direct", 0)
        chembl_direct = binder_counts.get("chembl_direct", 0)
        pdb_homolog = binder_counts.get("pdb_homolog", 0)
        chembl_homolog = binder_counts.get("chembl_homolog", 0)
        zinc_count = binder_counts.get("zinc", 0)
        direct_count = pdb_direct + chembl_direct
        homolog_count = pdb_homolog + chembl_homolog
        binder_count = direct_count + homolog_count + zinc_count

        if pdb_direct:
            score += 2.0
            _add_signal(signals, "Experimental PDB ligand")
        if chembl_direct:
            score += 2.0
            _add_signal(signals, "Measured ChEMBL activity")
        if homolog_count:
            score += 0.75
            _add_signal(signals, "Ligand evidence via homolog", "neutral")
        if zinc_count:
            score += 0.25
            _add_signal(signals, "ZINC proposed compounds", "neutral")

        if _is_no_hit(param_values.get("human_offtarget")):
            score += 1.5
            _add_signal(signals, "No similar human protein")
        elif str(param_values.get("human_offtarget") or "").strip().lower() == "hit":
            score -= 2.0
            _add_signal(cautions, "Human similarity", "bad")

        if _is_no_hit(param_values.get("gut_microbiome_offtarget")):
            score += 1.0
            _add_signal(signals, "No gut microbiome hit")
        elif str(param_values.get("gut_microbiome_offtarget") or "").strip().lower() == "hit":
            score -= 1.0
            _add_signal(cautions, "Gut microbiome similarity", "bad")

        if _is_yes(param_values.get("hit_in_deg")):
            score += 1.0
            _add_signal(signals, "Essential-gene similarity")

        if _is_core_call(param_values.get("core_roary")) and _is_core_call(param_values.get("core_corecruncher")):
            score += 1.0
            _add_signal(signals, "Core across strains")

        if gene_id in chokepoint_gene_ids:
            score += 1.5
            _add_signal(signals, "Metabolic chokepoint")
        elif gene_id in metabolic_gene_ids:
            score += 0.25
            _add_signal(signals, "Metabolic reaction", "neutral")

        if gene_id in proteins_with_experimental_structure:
            score += 1.0
            _add_signal(signals, "Experimental structure")
        elif gene_id in proteins_with_structure:
            score += 0.5
            _add_signal(signals, "Predicted 3D model", "neutral")

        if score <= 0 and not signals:
            continue

        shown_factors = (signals + cautions)[:6]
        scored.append({
            "protein": p,
            "score": score,
            "fpocket": fpocket or 0.0,
            "direct_count": direct_count,
            "binder_count": binder_count,
            "factors": shown_factors,
            "pdb_count": pdb_direct + pdb_homolog,
            "chembl_count": chembl_direct + chembl_homolog,
            "zinc_count": zinc_count,
        })

    return scored


def _format_score_items(scored_rows):
    items = []
    for row in scored_rows:
        p = row["protein"]
        tier_label, tier_tone = _evidence_convergence_tier(row["score"])
        items.append({
            "bioentry_id": p.bioentry_id,
            "accession": p.accession,
            "description": p.description,
            "score": round(row["score"], 1),
            "score_max": int(EVIDENCE_CONVERGENCE_MAX_SCORE),
            "score_percent": round((row["score"] / EVIDENCE_CONVERGENCE_MAX_SCORE) * 100),
            "tier_label": tier_label,
            "tier_tone": tier_tone,
            "factors": row["factors"],
            "binder_count": row["binder_count"],
            "direct_count": row["direct_count"],
            "druggability": row["fpocket"],
            "pdb_count": row["pdb_count"],
            "chembl_count": row["chembl_count"],
            "zinc_count": row["zinc_count"],
        })
    return items


def get_top_targets_by_score(assembly_name, user, limit=5):
    """Top-N proteins ranked by interpretable evidence convergence.

    This is not a saved ScoreFormula. It is a conservative overview heuristic
    that combines independent evidence streams so the genome page does not
    over-rank proteins by one raw signal such as FPocket or ligand count.
    """
    scored = _score_proteins(assembly_name)
    scored.sort(key=lambda r: (r["score"], r["fpocket"], r["direct_count"], r["binder_count"]), reverse=True)
    return {"formula_name": "Evidence convergence", "items": _format_score_items(scored[:limit])}


def get_unexplored_targets(assembly_name, user, limit=5):
    """Top-N proteins with strong non-chemical evidence but zero ligand records.

    Raw ligand count rewards "well-studied" proteins - a bacterial protein
    with a well-studied human homolog (kinases, GPCRs) racks up ChEMBL/ZINC
    hits regardless of whether it's a good bacterial-specific target, and that
    homology is often the same thing the off-target signal penalizes. This
    surfaces the inverse: promising, druggable, selective candidates nobody
    has drugged yet - a target-discovery view instead of a "most-studied" one.
    """
    scored = _score_proteins(assembly_name)
    unexplored = [r for r in scored if r["binder_count"] == 0]
    unexplored.sort(key=lambda r: (r["score"], r["fpocket"]), reverse=True)
    return {"formula_name": "Unexplored candidates", "items": _format_score_items(unexplored[:limit])}


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

    spv_qs = ScoreParamValue.objects.filter(bioentry__biodatabase__name=proteome_name)
    proteins_with_druggability = (
        spv_qs.filter(score_param__name="Druggability")
        .exclude(value__in=["", "nan", "None", "null"])
        .values("bioentry_id")
        .distinct()
        .count()
    )
    has_curated_data = spv_qs.filter(score_param__name="best_fpocket_structure").exists()

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

    metabolic_reactions_qs = MetabolicReaction.objects.filter(genome_accession=assembly_name)
    metabolic_reaction_count = metabolic_reactions_qs.count()
    metabolic_pathway_count = (
        metabolic_reactions_qs
        .filter(pathways__isnull=False)
        .values("pathways")
        .distinct()
        .count()
        if metabolic_reaction_count else 0
    )
    metabolic_links_qs = GeneReactionLink.objects.filter(reaction__genome_accession=assembly_name)
    metabolic_protein_count = (
        metabolic_links_qs.values("bioentry_id").distinct().count()
        if metabolic_reaction_count else 0
    )
    chokepoint_links_qs = metabolic_links_qs.exclude(chokepoint_role=GeneReactionLink.CHOKEPOINT_NONE)
    metabolic_chokepoint_gene_count = (
        chokepoint_links_qs.values("bioentry_id").distinct().count()
        if metabolic_reaction_count else 0
    )
    metabolic_chokepoint_reaction_count = (
        chokepoint_links_qs.values("reaction_id").distinct().count()
        if metabolic_reaction_count else 0
    )
    druggable_gene_ids = set(
        spv_qs
        .filter(score_param__name="Druggability", numeric_value__gte=0.4)
        .values_list("bioentry_id", flat=True)
    )
    chokepoint_gene_ids = set(
        chokepoint_links_qs.values_list("bioentry_id", flat=True)
    )
    metabolic_druggable_target_count = len(chokepoint_gene_ids & druggable_gene_ids)

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
        "proteins_with_druggability": proteins_with_druggability,
        "druggability_coverage_pct": _pct(proteins_with_druggability, total_proteins),
        "has_curated_data": has_curated_data,
        # legacy keys kept for backward compat
        "binder_pdb": binder_pdb_direct + binder_pdb_homolog,
        "binder_chembl": binder_chembl_direct + binder_chembl_homolog,
        "proteins_with_binders": proteins_with_binders,
        "binder_coverage_pct": _pct(proteins_with_binders, total_proteins),
        "metabolic_reaction_count": metabolic_reaction_count,
        "metabolic_pathway_count": metabolic_pathway_count,
        "metabolic_protein_count": metabolic_protein_count,
        "metabolic_coverage_pct": _pct(metabolic_protein_count, total_proteins),
        "metabolic_chokepoint_gene_count": metabolic_chokepoint_gene_count,
        "metabolic_chokepoint_reaction_count": metabolic_chokepoint_reaction_count,
        "metabolic_druggable_target_count": metabolic_druggable_target_count,
    }

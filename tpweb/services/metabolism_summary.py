from collections import defaultdict

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.protein_formula import choose_formula, coefficient_map, resolve_formulas_for_user
from tpweb.services.protein_serializer import compute_expression_score, compute_score_value, score_param_value_map


_CHOKEPOINT_PHRASES = {
    GeneReactionLink.CHOKEPOINT_PRODUCING: "a producing chokepoint reaction",
    GeneReactionLink.CHOKEPOINT_CONSUMING: "a consuming chokepoint reaction",
    GeneReactionLink.CHOKEPOINT_BOTH: "a producing & consuming chokepoint reaction",
}


def build_target_metabolic_sentence(metabolic_context, human_offtarget_no_hit=False):
    """Deterministic, template-based one-liner synthesizing signals ProteinView already
    computed (chokepoint role, pathway, centrality percentile, isoenzyme redundancy, human
    off-target) — the "so what" for a target, not just the raw network. No LLM involved."""
    chokepoint_reactions = [
        r for r in metabolic_context["reactions"] if r["chokepoint_role"] != GeneReactionLink.CHOKEPOINT_NONE
    ]
    parts = []

    if chokepoint_reactions:
        reaction = chokepoint_reactions[0]
        phrase = _CHOKEPOINT_PHRASES.get(reaction["chokepoint_role"], "a chokepoint reaction")
        pathways = metabolic_context.get("pathways") or []
        clause = f"catalyzes {phrase}"
        if pathways:
            clause += f" in {pathways[0]['name']}"
        parts.append(clause)
        if not reaction.get("has_isoenzyme_backup", True):
            parts.append("no isoenzyme backup detected")

    percentile = metabolic_context.get("centrality_percentile")
    if percentile is not None and percentile > 0:
        parts.append(f"more central than {percentile}% of genes in this genome")

    if human_offtarget_no_hit:
        parts.append("no human homolog detected")

    if not parts:
        return None

    lead = "Attractive metabolic target" if chokepoint_reactions else "Metabolic context"
    return f"{lead}: " + ", ".join(parts) + "."


def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _progress_width(value, min_value, max_value):
    if max_value <= min_value:
        return 100 if value > 0 else 0
    width = 100 * (value - min_value) / (max_value - min_value)
    return max(0, min(100, round(width, 1)))


def _score_maps(proteome_name):
    score_rows = (
        ScoreParamValue.objects
        .filter(
            bioentry__biodatabase__name=proteome_name,
            score_param__name__in=["Druggability", "p2rank_probability", "PTOOLS_betweenness_centrality"],
        )
        .select_related("score_param")
        .values("bioentry_id", "score_param__name", "numeric_value", "value")
    )
    raw_by_gene = defaultdict(dict)
    for row in score_rows:
        raw = row["numeric_value"] if row["numeric_value"] is not None else row["value"]
        raw_by_gene[row["bioentry_id"]][row["score_param__name"]] = raw

    # P2Rank is the primary druggability signal shown across the app -- prefer it here
    # too, falling back to FPocket's score only for proteins with no P2Rank value loaded.
    # Kept under the "Druggability" key so every existing caller (target_score heuristic,
    # top-target tiebreak, the "drug" chip on metabolism.html) picks it up unchanged.
    scores = defaultdict(dict)
    for gene_id, values in raw_by_gene.items():
        drugg_source = values.get("p2rank_probability")
        if drugg_source is None:
            drugg_source = values.get("Druggability")
        scores[gene_id]["Druggability"] = _to_float(drugg_source)
        if "PTOOLS_betweenness_centrality" in values:
            scores[gene_id]["PTOOLS_betweenness_centrality"] = _to_float(values["PTOOLS_betweenness_centrality"])
    return scores


def _resolve_scorer(user, formula_name):
    """Return a (score_fn, formula) pair. score_fn(protein) -> float, using the same
    term/expression evaluation ProteinListView uses for genome-wide ranking (bulk-prefetch
    friendly — no per-protein query), so pathway ranking reflects the user's own formula
    instead of a fixed heuristic."""
    formulas = resolve_formulas_for_user(user)
    formula = choose_formula(formulas, formula_name)
    if formula is None:
        return None, None

    formula_expression = (formula.expression or "").strip()
    if formula_expression:
        from tpweb.services.formula_evaluator import build_all_options_zero
        zero_cache = build_all_options_zero(user)

        def score_fn(protein):
            value, _ = compute_expression_score(protein, formula_expression, zero_cache)
            return value

        return score_fn, formula

    coefficient_by_param = coefficient_map(list(formula.terms.select_related("score_param")))

    def score_fn(protein):
        value, _ = compute_score_value(score_param_value_map(protein), coefficient_by_param)
        return value

    return score_fn, formula


def build_genome_metabolism_summary(assembly_name, user=None, formula_name=None, top_target_limit=5):
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    scores_by_protein = _score_maps(proteome_name)
    score_fn, active_formula = _resolve_scorer(user, formula_name)

    links = (
        GeneReactionLink.objects
        .filter(bioentry__biodatabase__name=proteome_name)
        .select_related("bioentry", "reaction")
        .prefetch_related(
            "reaction__pathways",
            "bioentry__score_params__score_param",
        )
    )
    pathway_map = {}
    unassigned = {
        "source": "MODEL",
        "external_id": "unassigned",
        "name": "Unassigned metabolic reactions",
        "reaction_ids": set(),
        "protein_ids": set(),
        "chokepoint_reaction_ids": set(),
        "target_rows": {},
    }

    for link in links:
        reaction = link.reaction
        pathways = list(reaction.pathways.all())
        target_pathways = pathways or [None]
        for pathway in target_pathways:
            if pathway is None:
                bucket = unassigned
            else:
                key = (pathway.source, pathway.external_id)
                bucket = pathway_map.setdefault(key, {
                    "source": pathway.source,
                    "external_id": pathway.external_id,
                    "name": pathway.name,
                    "reaction_ids": set(),
                    "protein_ids": set(),
                    "chokepoint_reaction_ids": set(),
                    "target_rows": {},
                })

            protein = link.bioentry
            protein_scores = scores_by_protein.get(protein.bioentry_id, {})
            druggability = protein_scores.get("Druggability", 0.0)
            centrality = protein_scores.get("PTOOLS_betweenness_centrality", 0.0)
            is_chokepoint = link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE
            if score_fn is not None:
                target_score = score_fn(protein)
            else:
                # No formula selected/available: fall back to a fixed heuristic so the
                # page still ranks something sensible.
                target_score = druggability + (0.15 if is_chokepoint else 0.0) + min(centrality, 1.0) * 0.1

            bucket["reaction_ids"].add(reaction.id)
            bucket["protein_ids"].add(protein.bioentry_id)
            if is_chokepoint:
                bucket["chokepoint_reaction_ids"].add(reaction.id)

            target = bucket["target_rows"].get(protein.bioentry_id)
            if target is None or target_score > target["target_score"]:
                bucket["target_rows"][protein.bioentry_id] = {
                    "protein_id": protein.bioentry_id,
                    "accession": protein.accession,
                    "description": protein.description or "",
                    "druggability": druggability,
                    "centrality": centrality,
                    "is_chokepoint": is_chokepoint,
                    "target_score": target_score,
                }

    buckets = list(pathway_map.values())
    if unassigned["reaction_ids"]:
        buckets.append(unassigned)

    pathways = []
    total_reactions = set()
    total_proteins = set()
    total_chokepoints = set()
    for bucket in buckets:
        top_targets = sorted(
            bucket["target_rows"].values(),
            key=lambda t: (t["target_score"], t["druggability"], t["centrality"]),
            reverse=True,
        )[:top_target_limit]
        reaction_count = len(bucket["reaction_ids"])
        protein_count = len(bucket["protein_ids"])
        chokepoint_count = len(bucket["chokepoint_reaction_ids"])
        total_reactions.update(bucket["reaction_ids"])
        total_proteins.update(bucket["protein_ids"])
        total_chokepoints.update(bucket["chokepoint_reaction_ids"])
        best_score = top_targets[0]["target_score"] if top_targets else 0.0
        target_scores = [target["target_score"] for target in bucket["target_rows"].values()]
        mean_score = sum(target_scores) / len(target_scores) if target_scores else 0.0
        chokepoint_density = chokepoint_count / reaction_count if reaction_count else 0.0
        # Full protein list (not just top_targets, which is capped to top_target_limit) so
        # client-side search can match any protein in the pathway, not only the handful
        # shown as chips.
        protein_search_blob = " ".join(sorted(
            f"{t['accession']} {t['description']}".lower()
            for t in bucket["target_rows"].values()
        ))
        pathways.append({
            "source": bucket["source"],
            "external_id": bucket["external_id"],
            "name": bucket["name"],
            "reaction_count": reaction_count,
            "protein_count": protein_count,
            "chokepoint_count": chokepoint_count,
            "chokepoint_density": round(chokepoint_density, 3),
            "chokepoint_density_pct": round(100 * chokepoint_density, 1),
            "best_target_score": round(best_score, 3),
            "mean_target_score": round(mean_score, 3),
            "top_targets": top_targets,
            "protein_search_blob": protein_search_blob,
        })

    pathways.sort(
        key=lambda p: (
            p["chokepoint_density"],
            p["best_target_score"],
            p["chokepoint_count"],
            p["protein_count"],
            p["reaction_count"],
        ),
        reverse=True,
    )
    positive_best_scores = [p["best_target_score"] for p in pathways if p["best_target_score"] > 0]
    min_positive_score = min(positive_best_scores, default=0.0)
    max_positive_score = max(positive_best_scores, default=0.0)
    for pathway in pathways:
        pathway["best_target_score_width"] = _progress_width(
            pathway["best_target_score"],
            min_positive_score,
            max_positive_score,
        )

    return {
        "pathways": pathways,
        "pathway_count": len(pathways),
        "reaction_count": len(total_reactions),
        "protein_count": len(total_proteins),
        "chokepoint_count": len(total_chokepoints),
        "active_formula_name": active_formula.name if active_formula else None,
    }

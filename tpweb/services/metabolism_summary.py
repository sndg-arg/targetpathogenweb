from collections import defaultdict

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink
from tpweb.models.ScoreParamValue import ScoreParamValue


def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _score_maps(proteome_name):
    score_rows = (
        ScoreParamValue.objects
        .filter(
            bioentry__biodatabase__name=proteome_name,
            score_param__name__in=["Druggability", "PTOOLS_betweenness_centrality"],
        )
        .select_related("score_param")
        .values("bioentry_id", "score_param__name", "numeric_value", "value")
    )
    scores = defaultdict(dict)
    for row in score_rows:
        raw = row["numeric_value"] if row["numeric_value"] is not None else row["value"]
        scores[row["bioentry_id"]][row["score_param__name"]] = _to_float(raw)
    return scores


def build_genome_metabolism_summary(assembly_name, top_target_limit=5):
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    scores_by_protein = _score_maps(proteome_name)

    links = (
        GeneReactionLink.objects
        .filter(bioentry__biodatabase__name=proteome_name)
        .select_related("bioentry", "reaction")
        .prefetch_related("reaction__pathways")
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
        pathways.append({
            "source": bucket["source"],
            "external_id": bucket["external_id"],
            "name": bucket["name"],
            "reaction_count": reaction_count,
            "protein_count": protein_count,
            "chokepoint_count": chokepoint_count,
            "best_target_score": round(best_score, 3),
            "top_targets": top_targets,
        })

    pathways.sort(
        key=lambda p: (p["chokepoint_count"], p["best_target_score"], p["protein_count"], p["reaction_count"]),
        reverse=True,
    )

    return {
        "pathways": pathways,
        "pathway_count": len(pathways),
        "reaction_count": len(total_reactions),
        "protein_count": len(total_proteins),
        "chokepoint_count": len(total_chokepoints),
    }

"""Genome-wide pathway-level metabolic network graph.

Unlike build_genome_metabolism_summary (metabolism_summary.py), which assigns a reaction
to EVERY pathway it belongs to (multi-membership, fine for a ranked browse list), this
module assigns each reaction to exactly ONE pathway -- a strict partition. A graph needs
that: a collapsed pathway node's reaction_count must match exactly what expanding it
reveals, and a pathway-to-pathway edge (built from MetabolicReactionEdge, which is
reaction-to-reaction) needs an unambiguous single bucket on each side. The two aggregations
are deliberately separate functions/files rather than one parametrized function, so a
future change to the ranking list's scoring logic doesn't have to reason about graph
correctness, and vice versa.
"""
from collections import Counter, defaultdict

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink, MetabolicReaction, MetabolicReactionEdge
from tpweb.services.metabolism_summary import _resolve_scorer, _score_maps


def _primary_pathway_buckets(assembly_name):
    """One primary pathway per reaction: alphabetically-first (source, external_id), or the
    MODEL/unassigned bucket if the reaction has no pathway membership at all. Returns
    {reaction_id: (source, external_id, name)}. Shared by build_genome_metabolism_network
    and MetabolismNetworkExpandView so a node's stats and its expansion always agree."""
    buckets = {}
    reactions = (
        MetabolicReaction.objects
        .filter(genome_accession=assembly_name)
        .prefetch_related("pathways")
    )
    for reaction in reactions:
        pathways = sorted(reaction.pathways.all(), key=lambda p: (p.source, p.external_id))
        if pathways:
            pathway = pathways[0]
            buckets[reaction.id] = (pathway.source, pathway.external_id, pathway.name)
        else:
            buckets[reaction.id] = ("MODEL", "unassigned", "Unassigned metabolic reactions")
    return buckets


def build_genome_metabolism_network(assembly_name, user=None, formula_name=None, top_target_limit=5):
    """{"nodes": [...one per pathway bucket...], "edges": [...weighted pathway-pair edges...],
    "active_formula_name"}. Node stats mirror build_genome_metabolism_summary's per-pathway
    fields (reaction/protein/chokepoint counts, best/mean target score, top_targets) but
    computed under the strict _primary_pathway_buckets partition -- these numbers will not
    always exactly match the ranking list's numbers for pathways that share reactions with
    another pathway; that divergence is expected, not a bug (see module docstring)."""
    proteome_name = assembly_name + Biodatabase.PROT_POSTFIX
    reaction_bucket = _primary_pathway_buckets(assembly_name)

    scores_by_protein = _score_maps(proteome_name)
    score_fn, active_formula = _resolve_scorer(user, formula_name)

    links = (
        GeneReactionLink.objects
        .filter(bioentry__biodatabase__name=proteome_name, reaction_id__in=reaction_bucket.keys())
        .select_related("bioentry", "reaction")
        .prefetch_related("bioentry__score_params__score_param")
    )

    buckets = defaultdict(lambda: {
        "name": "",
        "reaction_ids": set(),
        "protein_ids": set(),
        "chokepoint_reaction_ids": set(),
        "target_rows": {},
    })

    for link in links:
        reaction = link.reaction
        source, external_id, name = reaction_bucket[reaction.id]
        key = (source, external_id)
        bucket = buckets[key]
        bucket["name"] = name

        protein = link.bioentry
        protein_scores = scores_by_protein.get(protein.bioentry_id, {})
        druggability = protein_scores.get("Druggability", 0.0)
        centrality = protein_scores.get("PTOOLS_betweenness_centrality", 0.0)
        is_chokepoint = link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE
        if score_fn is not None:
            target_score = score_fn(protein)
        else:
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

    nodes = []
    node_ids = set()
    for key, bucket in buckets.items():
        top_targets = sorted(
            bucket["target_rows"].values(),
            key=lambda t: (t["target_score"], t["druggability"], t["centrality"]),
            reverse=True,
        )[:top_target_limit]
        reaction_count = len(bucket["reaction_ids"])
        chokepoint_count = len(bucket["chokepoint_reaction_ids"])
        chokepoint_density = chokepoint_count / reaction_count if reaction_count else 0.0
        target_scores = [t["target_score"] for t in bucket["target_rows"].values()]
        best_score = top_targets[0]["target_score"] if top_targets else 0.0
        mean_score = sum(target_scores) / len(target_scores) if target_scores else 0.0
        node_id = f"{key[0]}__{key[1]}"
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "source": key[0],
            "external_id": key[1],
            "name": bucket["name"],
            "reaction_count": reaction_count,
            "protein_count": len(bucket["protein_ids"]),
            "chokepoint_count": chokepoint_count,
            "chokepoint_density_pct": round(100 * chokepoint_density, 1),
            "best_target_score": round(best_score, 3),
            "mean_target_score": round(mean_score, 3),
            "top_targets": top_targets,
        })

    edge_counter = Counter()
    edge_rows = MetabolicReactionEdge.objects.filter(
        genome_accession=assembly_name,
    ).values_list("reaction_a_id", "reaction_b_id")
    for reaction_a_id, reaction_b_id in edge_rows:
        bucket_a = reaction_bucket.get(reaction_a_id)
        bucket_b = reaction_bucket.get(reaction_b_id)
        if bucket_a is None or bucket_b is None:
            continue
        id_a = f"{bucket_a[0]}__{bucket_a[1]}"
        id_b = f"{bucket_b[0]}__{bucket_b[1]}"
        if id_a == id_b:
            continue
        edge_counter[tuple(sorted([id_a, id_b]))] += 1

    edges = [
        {"source": pair[0], "target": pair[1], "weight": weight}
        for pair, weight in edge_counter.items()
        # Defensive: both endpoints must correspond to an actual node (a pathway bucket
        # with zero gene-linked reactions has no node, per build_genome_metabolism_summary's
        # same pre-existing GeneReactionLink-driven limitation) -- an edge to a
        # non-existent node would break the Cytoscape graph on the frontend.
        if pair[0] in node_ids and pair[1] in node_ids
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "active_formula_name": active_formula.name if active_formula else None,
    }


def pathway_neighbors(assembly_name, source, external_id, user=None, formula_name=None):
    """Direct neighbors of one pathway (pathways it shares reaction-reaction adjacency
    with), filtered from the exact same genome-wide network build_genome_metabolism_network
    already computes for the "all pathways" page -- no separate heavy computation. Returns a
    list of {"source", "external_id", "name", "reaction_count", "shared_weight"} sorted by
    shared_weight descending, or [] if the pathway has no gene-linked reactions (so it never
    got a node in the network to begin with)."""
    network = build_genome_metabolism_network(assembly_name, user=user, formula_name=formula_name)
    node_id = f"{source}__{external_id}"
    nodes_by_id = {node["id"]: node for node in network["nodes"]}
    if node_id not in nodes_by_id:
        return []

    neighbors = []
    for edge in network["edges"]:
        if edge["source"] == node_id:
            other_id = edge["target"]
        elif edge["target"] == node_id:
            other_id = edge["source"]
        else:
            continue
        other = nodes_by_id.get(other_id)
        if not other:
            continue
        neighbors.append({
            "source": other["source"],
            "external_id": other["external_id"],
            "name": other["name"],
            "reaction_count": other["reaction_count"],
            "shared_weight": edge["weight"],
        })
    neighbors.sort(key=lambda n: n["shared_weight"], reverse=True)
    return neighbors

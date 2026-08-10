from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import (
    GeneReactionLink,
    MetabolicReaction,
    MetabolicReactionEdge,
    ReactionParticipant,
)
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    user_can_access_genome_name,
)
from tpweb.services.protein_summary import build_metabolic_context

MAX_HOPS = 2
MAX_NODES = 60


def _resolve_edge_direction(a_id, b_id, participant_roles):
    """Real reactant->product direction between two reactions that share a
    metabolite, derived from ReactionParticipant roles -- not the arbitrary
    a/b order MetabolicReactionEdge stores (inherited from the network.sif
    adjacency file). Returns (source_id, target_id) or None if direction
    can't be determined (no shared species data, or votes from multiple
    shared metabolites disagree -- a genuine cycle/ambiguous case, left
    undirected rather than guessed)."""
    roles_a = participant_roles.get(a_id, {})
    roles_b = participant_roles.get(b_id, {})
    shared = set(roles_a) & set(roles_b)
    if not shared:
        return None
    # Prefer pathway-specific metabolites over currency cofactors (ATP,
    # water, NAD+, ...) for the direction signal -- shared currency
    # metabolites are common to unrelated reactions and are a weak/noisy
    # signal of real pathway order.
    candidates = {sid for sid in shared if not roles_a[sid][1]} or shared
    forward = backward = 0
    for sid in candidates:
        role_a, _ = roles_a[sid]
        role_b, _ = roles_b[sid]
        if (
            role_a == ReactionParticipant.ROLE_PRODUCT
            and role_b == ReactionParticipant.ROLE_REACTANT
        ):
            forward += 1
        elif (
            role_a == ReactionParticipant.ROLE_REACTANT
            and role_b == ReactionParticipant.ROLE_PRODUCT
        ):
            backward += 1
    if forward and not backward:
        return (a_id, b_id)
    if backward and not forward:
        return (b_id, a_id)
    return None


class MetabolismNetworkView(View):
    """JSON ego-network (reactions within a couple of hops) for the Cytoscape.js diagram
    on the protein detail page."""

    def get(self, request, protein_id, *args, **kwargs):
        protein = (
            Bioentry.objects.filter(bioentry_id=protein_id).select_related("biodatabase").first()
        )
        if protein is None:
            raise Http404("Protein not found")

        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Protein not found")

        focal_reaction_ids = set(
            GeneReactionLink.objects.filter(bioentry=protein).values_list("reaction_id", flat=True)
        )
        if not focal_reaction_ids:
            return JsonResponse({"nodes": [], "edges": []})

        genome_accession = assembly_name
        node_ids, edge_pairs, truncated = self._expand_neighborhood(
            genome_accession, focal_reaction_ids
        )

        reactions = {
            r.id: r
            for r in MetabolicReaction.objects.filter(id__in=node_ids).prefetch_related("pathways")
        }
        edge_pairs = {(a, b) for a, b in edge_pairs if a in reactions and b in reactions}

        genes_by_reaction = {}
        for link in GeneReactionLink.objects.filter(
            reaction_id__in=reactions.keys()
        ).select_related("bioentry"):
            genes_by_reaction.setdefault(link.reaction_id, []).append(link)

        participant_roles = {}
        for p in ReactionParticipant.objects.filter(
            reaction_id__in=reactions.keys()
        ).select_related("species"):
            participant_roles.setdefault(p.reaction_id, {})[p.species_id] = (
                p.role,
                p.species.is_currency,
            )

        nodes = [
            self._serialize_node(
                reaction_id,
                reaction,
                genes_by_reaction.get(reaction_id, []),
                edge_pairs,
                focal_reaction_ids,
                protein.bioentry_id,
            )
            for reaction_id, reaction in reactions.items()
        ]
        edges = []
        for a, b in edge_pairs:
            direction = _resolve_edge_direction(a, b, participant_roles)
            src_id, tgt_id = direction if direction else (a, b)
            edges.append(
                {
                    "source": reactions[src_id].reaction_id,
                    "target": reactions[tgt_id].reaction_id,
                    "directed": direction is not None,
                    "reversible": reactions[a].reversible or reactions[b].reversible,
                }
            )
        return JsonResponse(
            {
                "nodes": nodes,
                "edges": edges,
                "meta": {
                    "max_hops": MAX_HOPS,
                    "max_nodes": MAX_NODES,
                    "is_truncated": truncated,
                    "genome_slug": genome_url_slug(assembly_name),
                },
            }
        )

    @staticmethod
    def _expand_neighborhood(genome_accession, focal_reaction_ids):
        node_ids = set(focal_reaction_ids)
        frontier = set(focal_reaction_ids)
        edge_pairs = set()
        truncated = False

        for _ in range(MAX_HOPS):
            if not frontier or len(node_ids) >= MAX_NODES:
                truncated = bool(frontier and len(node_ids) >= MAX_NODES)
                break
            neighbor_edges = (
                MetabolicReactionEdge.objects.filter(
                    genome_accession=genome_accession,
                )
                .filter(Q(reaction_a_id__in=frontier) | Q(reaction_b_id__in=frontier))
                .values_list("reaction_a_id", "reaction_b_id")
            )

            next_frontier = set()
            for a_id, b_id in neighbor_edges:
                edge_pairs.add((a_id, b_id))
                for node_id in (a_id, b_id):
                    if node_id not in node_ids and len(node_ids) < MAX_NODES:
                        node_ids.add(node_id)
                        next_frontier.add(node_id)
                    elif node_id not in node_ids:
                        truncated = True
            frontier = next_frontier

        return node_ids, edge_pairs, truncated

    @staticmethod
    def _serialize_node(
        reaction_id, reaction, links, edge_pairs, focal_reaction_ids, current_protein_id
    ):
        chokepoint_role = next(
            (
                link.chokepoint_role
                for link in links
                if link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE
            ),
            GeneReactionLink.CHOKEPOINT_NONE,
        )
        return {
            "id": reaction.reaction_id,
            "name": reaction.name or reaction.reaction_id,
            "ec_numbers": reaction.ec_numbers,
            "kegg_reaction_id": reaction.kegg_reaction_id,
            "reversible": reaction.reversible,
            "chokepoint_role": chokepoint_role,
            "isoenzyme_count": reaction.isoenzyme_count,
            "pathways": [
                {"source": p.source, "external_id": p.external_id, "name": p.name}
                for p in reaction.pathways.all()
            ],
            "is_focal": reaction_id in focal_reaction_ids,
            "degree": sum(1 for a, b in edge_pairs if reaction_id in (a, b)),
            "genes": [
                {
                    "locus_tag": link.bioentry.accession,
                    "protein_id": link.bioentry.bioentry_id,
                    "is_current_protein": link.bioentry.bioentry_id == current_protein_id,
                    "url": reverse(
                        "tpwebapp:protein", kwargs={"protein_id": link.bioentry.bioentry_id}
                    ),
                }
                for link in links
            ],
        }


class ProteinMetabolicNetworkPageView(View):
    """Full-page metabolic reaction list + ego-network graph for one protein --
    the "premium" counterpart to the light preview embedded in the protein
    detail page's Metabolic context section (same split as structure.html vs.
    the embedded structure preview)."""

    template_name = "genomic/protein_metabolic_network.html"

    def get(self, request, protein_id, *args, **kwargs):
        protein = (
            Bioentry.objects.filter(bioentry_id=protein_id).select_related("biodatabase").first()
        )
        if protein is None:
            raise Http404("Protein not found")

        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Protein not found")

        raw_scores = {
            spv.score_param.name: spv.value
            if spv.value
            else (str(round(spv.numeric_value, 4)) if spv.numeric_value is not None else "")
            for spv in ScoreParamValue.objects.filter(bioentry=protein).select_related(
                "score_param"
            )
        }
        metabolic_context = build_metabolic_context(protein, raw_scores)
        if metabolic_context is None:
            raise Http404("No metabolic data for this protein")

        slug = genome_url_slug(assembly_name)
        return render(
            request,
            self.template_name,
            {
                "protein": protein,
                "metabolic_context": metabolic_context,
                "assembly_name": display_genome_name(assembly_name),
                "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
                "protein_url": reverse(
                    "tpwebapp:protein", kwargs={"protein_id": protein.bioentry_id}
                ),
            },
        )

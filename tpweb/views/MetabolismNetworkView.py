from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink, MetabolicReaction, MetabolicReactionEdge
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, user_can_access_genome_name
from tpweb.services.protein_summary import build_metabolic_context

MAX_HOPS = 2
MAX_NODES = 60


class MetabolismNetworkView(View):
    """JSON ego-network (reactions within a couple of hops) for the Cytoscape.js diagram
    on the protein detail page."""

    def get(self, request, protein_id, *args, **kwargs):
        protein = Bioentry.objects.filter(bioentry_id=protein_id).select_related("biodatabase").first()
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
        node_ids, edge_pairs, truncated = self._expand_neighborhood(genome_accession, focal_reaction_ids)

        reactions = {
            r.id: r
            for r in MetabolicReaction.objects.filter(id__in=node_ids).prefetch_related("pathways")
        }
        edge_pairs = {(a, b) for a, b in edge_pairs if a in reactions and b in reactions}

        genes_by_reaction = {}
        for link in GeneReactionLink.objects.filter(reaction_id__in=reactions.keys()).select_related("bioentry"):
            genes_by_reaction.setdefault(link.reaction_id, []).append(link)

        nodes = [
            self._serialize_node(reaction_id, reaction, genes_by_reaction.get(reaction_id, []),
                                  edge_pairs, focal_reaction_ids, protein.bioentry_id)
            for reaction_id, reaction in reactions.items()
        ]
        edges = [
            {"source": reactions[a].reaction_id, "target": reactions[b].reaction_id}
            for a, b in edge_pairs
        ]
        return JsonResponse({
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "max_hops": MAX_HOPS,
                "max_nodes": MAX_NODES,
                "is_truncated": truncated,
                "genome_slug": genome_url_slug(assembly_name),
            },
        })

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
            neighbor_edges = MetabolicReactionEdge.objects.filter(
                genome_accession=genome_accession,
            ).filter(
                Q(reaction_a_id__in=frontier) | Q(reaction_b_id__in=frontier)
            ).values_list("reaction_a_id", "reaction_b_id")

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
    def _serialize_node(reaction_id, reaction, links, edge_pairs, focal_reaction_ids, current_protein_id):
        chokepoint_role = next(
            (l.chokepoint_role for l in links if l.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE),
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
                    "locus_tag": l.bioentry.accession,
                    "protein_id": l.bioentry.bioentry_id,
                    "is_current_protein": l.bioentry.bioentry_id == current_protein_id,
                    "url": reverse("tpwebapp:protein", kwargs={"protein_id": l.bioentry.bioentry_id}),
                }
                for l in links
            ],
        }


class ProteinMetabolicNetworkPageView(View):
    """Full-page metabolic reaction list + ego-network graph for one protein --
    the "premium" counterpart to the light preview embedded in the protein
    detail page's Metabolic context section (same split as structure.html vs.
    the embedded structure preview)."""

    template_name = "genomic/protein_metabolic_network.html"

    def get(self, request, protein_id, *args, **kwargs):
        protein = Bioentry.objects.filter(bioentry_id=protein_id).select_related("biodatabase").first()
        if protein is None:
            raise Http404("Protein not found")

        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Protein not found")

        raw_scores = {
            spv.score_param.name: spv.value if spv.value else (
                str(round(spv.numeric_value, 4)) if spv.numeric_value is not None else ""
            )
            for spv in ScoreParamValue.objects.filter(bioentry=protein).select_related("score_param")
        }
        metabolic_context = build_metabolic_context(protein, raw_scores)
        if metabolic_context is None:
            raise Http404("No metabolic data for this protein")

        slug = genome_url_slug(assembly_name)
        return render(request, self.template_name, {
            "protein": protein,
            "metabolic_context": metabolic_context,
            "assembly_name": display_genome_name(assembly_name),
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
            "protein_url": reverse("tpwebapp:protein", kwargs={"protein_id": protein.bioentry_id}),
        })

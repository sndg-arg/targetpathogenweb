from collections import defaultdict

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink, MetabolicPathway, MetabolicReaction
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.metabolism_summary import build_genome_metabolism_summary
from tpweb.services.metabolism_network import (
    _primary_pathway_buckets,
    build_genome_metabolism_network,
    pathway_neighbors,
)


class MetabolismPathwayView(View):
    template_name = "genomic/metabolism.html"

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        try:
            biodb = Biodatabase.objects.get(name=assembly_name)
        except Biodatabase.DoesNotExist as exc:
            raise Http404("Genome not found") from exc

        slug = genome_url_slug(assembly_name)
        formula_name = request.GET.get("scoreformula") or None
        summary = build_genome_metabolism_summary(
            assembly_name, user=request.user, formula_name=formula_name
        )

        # Reuse the same genome-wide network the "view as network" page builds, just to
        # count each pathway's direct connections -- one build, not one per pathway row.
        # build_genome_metabolism_summary uses multi-membership (a reaction can count
        # toward every pathway it belongs to) while the network uses a strict one-pathway
        # partition, so not every ranked pathway here is guaranteed a matching network node;
        # those simply show 0 connections rather than erroring.
        network = build_genome_metabolism_network(
            assembly_name, user=request.user, formula_name=formula_name
        )
        connection_counts = defaultdict(int)
        for edge in network["edges"]:
            connection_counts[edge["source"]] += 1
            connection_counts[edge["target"]] += 1
        for pathway in summary["pathways"]:
            node_id = f"{pathway['source']}__{pathway['external_id']}"
            pathway["connections_count"] = connection_counts.get(node_id, 0)

        return render(
            request,
            self.template_name,
            {
                "assembly": {
                    "name": display_genome_name(assembly_name),
                    "internal_name": assembly_name,
                    "slug": slug,
                    "description": biodb.description,
                },
                "summary": summary,
                "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
                "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
            },
        )


def _participant_payload(participants, role):
    rows = []
    for participant in participants:
        if participant.role != role:
            continue
        species = participant.species
        rows.append(
            {
                "name": species.display_name or species.species_id,
                "species_id": species.species_id,
                "compartment": species.compartment or "model",
                "is_currency": species.is_currency,
                "stoichiometry": participant.stoichiometry,
            }
        )
    rows.sort(key=lambda p: (p["is_currency"], p["name"]))
    return rows


def _compact_participants(rows, limit=8):
    visible = rows[:limit]
    hidden = max(0, len(rows) - len(visible))
    return visible, hidden


def _build_reaction_row(reaction):
    links = list(reaction.genes.all())
    participants = list(reaction.participants.all())
    substrates = _participant_payload(participants, "reactant")
    products = _participant_payload(participants, "product")
    substrate_visible, substrate_hidden = _compact_participants(substrates)
    product_visible, product_hidden = _compact_participants(products)
    chokepoint_role = next(
        (
            link.chokepoint_role
            for link in links
            if link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE
        ),
        GeneReactionLink.CHOKEPOINT_NONE,
    )
    genes = [
        {
            "accession": link.bioentry.accession,
            "protein_id": link.bioentry.bioentry_id,
            "url": reverse("tpwebapp:protein", kwargs={"protein_id": link.bioentry.bioentry_id}),
        }
        for link in links
    ]
    genes.sort(key=lambda g: g["accession"])
    return {
        "id": reaction.reaction_id,
        "name": reaction.name or reaction.reaction_id,
        "ec_numbers": [ec for ec in (reaction.ec_numbers or "").split(",") if ec],
        "kegg_reaction_id": reaction.kegg_reaction_id,
        "kegg_url": f"https://www.kegg.jp/entry/{reaction.kegg_reaction_id}"
        if reaction.kegg_reaction_id
        else "",
        # reaction_id is already the BioCyc/MetaCyc frame id -- always buildable, unlike
        # kegg_url which depends on a KEGG annotation being present in the source SBML.
        "metacyc_url": f"https://metacyc.org/META/NEW-IMAGE?type=REACTION&object={reaction.reaction_id}",
        "reversible": reaction.reversible,
        "isoenzyme_count": reaction.isoenzyme_count,
        "chokepoint_role": chokepoint_role,
        "is_chokepoint": chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE,
        "genes": genes,
        "substrates": substrate_visible,
        "products": product_visible,
        "substrate_hidden": substrate_hidden,
        "product_hidden": product_hidden,
        "substrate_count": len(substrates),
        "product_count": len(products),
    }


def _reaction_topology_row(reaction):
    """Like _build_reaction_row, but without the substrate/product participant queries a
    graph topology node never needs -- calling _build_reaction_row and discarding those
    fields would still pay for reaction.participants.all() on every reaction for nothing."""
    links = list(reaction.genes.all())
    chokepoint_role = next(
        (
            link.chokepoint_role
            for link in links
            if link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE
        ),
        GeneReactionLink.CHOKEPOINT_NONE,
    )
    genes = [
        {
            "accession": link.bioentry.accession,
            "protein_id": link.bioentry.bioentry_id,
            "url": reverse("tpwebapp:protein", kwargs={"protein_id": link.bioentry.bioentry_id}),
        }
        for link in links
    ]
    genes.sort(key=lambda g: g["accession"])
    return {
        "id": reaction.reaction_id,
        "name": reaction.name or reaction.reaction_id,
        "ec_numbers": [ec for ec in (reaction.ec_numbers or "").split(",") if ec],
        "reversible": reaction.reversible,
        "chokepoint_role": chokepoint_role,
        "is_chokepoint": chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE,
        "isoenzyme_count": reaction.isoenzyme_count,
        "genes": genes,
    }


class MetabolismPathwayDetailView(View):
    template_name = "genomic/metabolism_pathway.html"

    def get(self, request, genome, source, external_id, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        try:
            biodb = Biodatabase.objects.get(name=assembly_name)
        except Biodatabase.DoesNotExist as exc:
            raise Http404("Genome not found") from exc

        source = source.upper()
        if source == "MODEL" and external_id == "unassigned":
            pathway = {
                "source": "MODEL",
                "external_id": "unassigned",
                "name": "Unassigned metabolic reactions",
            }
            reactions_qs = MetabolicReaction.objects.filter(
                genome_accession=assembly_name,
                pathways__isnull=True,
            )
        else:
            try:
                pathway_obj = MetabolicPathway.objects.get(source=source, external_id=external_id)
            except MetabolicPathway.DoesNotExist as exc:
                raise Http404("Pathway not found") from exc
            pathway = {
                "source": pathway_obj.source,
                "external_id": pathway_obj.external_id,
                "name": pathway_obj.name,
            }
            reactions_qs = pathway_obj.reactions.filter(genome_accession=assembly_name)

        reactions = list(
            reactions_qs.distinct()
            .prefetch_related("participants__species", "genes__bioentry")
            .order_by("reaction_id")
        )
        if not reactions:
            raise Http404("Pathway not found for this genome")

        reaction_rows = [_build_reaction_row(reaction) for reaction in reactions]
        protein_ids = {gene["protein_id"] for row in reaction_rows for gene in row["genes"]}
        metabolite_ids = {
            participant.species.species_id
            for reaction in reactions
            for participant in reaction.participants.all()
        }
        chokepoint_count = sum(1 for row in reaction_rows if row["is_chokepoint"])
        # When a pathway has more reactions than the graph can show legibly, prioritize
        # chokepoints so the most decision-relevant nodes aren't cut by alphabetical luck.
        diagram_candidates = sorted(
            reaction_rows, key=lambda r: (not r["is_chokepoint"], r["name"])
        )
        diagram_reactions = diagram_candidates[:45]
        omitted_reactions = max(0, len(reaction_rows) - len(diagram_reactions))
        diagram_reaction_ids = {row["id"] for row in diagram_reactions}
        diagram_reaction_objects = [r for r in reactions if r.reaction_id in diagram_reaction_ids]
        slug = genome_url_slug(assembly_name)

        connected_pathways = [
            {
                "name": neighbor["name"],
                "source": neighbor["source"],
                "external_id": neighbor["external_id"],
                "reaction_count": neighbor["reaction_count"],
                "shared_weight": neighbor["shared_weight"],
                "url": reverse(
                    "tpwebapp:genome_metabolism_pathway",
                    kwargs={
                        "genome": slug,
                        "source": neighbor["source"],
                        "external_id": neighbor["external_id"],
                    },
                ),
            }
            for neighbor in pathway_neighbors(assembly_name, source, external_id, user=request.user)
        ]

        return render(
            request,
            self.template_name,
            {
                "assembly": {
                    "name": display_genome_name(assembly_name),
                    "internal_name": assembly_name,
                    "slug": slug,
                    "description": biodb.description,
                },
                "pathway": pathway,
                "stats": {
                    "reaction_count": len(reaction_rows),
                    "protein_count": len(protein_ids),
                    "metabolite_count": len(metabolite_ids),
                    "chokepoint_count": chokepoint_count,
                },
                "reaction_rows": reaction_rows,
                "connected_pathways": connected_pathways,
                "graph_payload": _reaction_metabolite_graph(diagram_reaction_objects),
                "omitted_reactions": omitted_reactions,
                "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
                "metabolism_url": reverse("tpwebapp:genome_metabolism", kwargs={"genome": slug}),
                "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
            },
        )


class MetabolismNetworkPageView(View):
    """Genome-wide unified metabolic network graph (pathway-level nodes, expand-in-place
    on click) -- an additional way to explore the same data as MetabolismPathwayView's
    ranking list and MetabolismPathwayDetailView's per-pathway SVG diagram, not a
    replacement for either."""

    template_name = "genomic/metabolism_network.html"

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        try:
            biodb = Biodatabase.objects.get(name=assembly_name)
        except Biodatabase.DoesNotExist as exc:
            raise Http404("Genome not found") from exc

        slug = genome_url_slug(assembly_name)
        # Genome totals only, for the 4 metric pills -- the graph itself is fetched
        # client-side from MetabolismNetworkGraphView. These are page-level totals, so the
        # multi-membership-vs-partition distinction between build_genome_metabolism_summary
        # and build_genome_metabolism_network doesn't apply here.
        summary = build_genome_metabolism_summary(assembly_name, user=request.user)
        return render(
            request,
            self.template_name,
            {
                "assembly": {
                    "name": display_genome_name(assembly_name),
                    "internal_name": assembly_name,
                    "slug": slug,
                    "description": biodb.description,
                },
                "summary": summary,
                "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
                "metabolism_url": reverse("tpwebapp:genome_metabolism", kwargs={"genome": slug}),
                "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
                "network_data_url": reverse(
                    "tpwebapp:genome_metabolism_network_data", kwargs={"genome": slug}
                ),
                "network_expand_url_template": reverse(
                    "tpwebapp:genome_metabolism_network_expand",
                    kwargs={
                        "genome": slug,
                        "source": "__SOURCE__",
                        "external_id": "__EXTERNAL_ID__",
                    },
                ),
            },
        )


class MetabolismNetworkGraphView(View):
    """JSON: the collapsed, genome-wide pathway-level graph (nodes + weighted cross-pathway
    edges) for MetabolismNetworkPageView's Cytoscape canvas."""

    def get(self, request, genome, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        formula_name = request.GET.get("scoreformula") or None
        payload = build_genome_metabolism_network(
            assembly_name, user=request.user, formula_name=formula_name
        )
        return JsonResponse(payload)


def _reaction_metabolite_graph(reactions):
    """Reaction+metabolite bipartite graph for one pathway's reactions: every metabolite
    that appears as a substrate/product of ANY of these reactions becomes one shared node
    (deduplicated by species_id), so a metabolite produced by one reaction and consumed by
    another renders as a single connecting node -- this is what makes it a real graph
    instead of isolated per-reaction chip rows. Used both by the unified network's
    expand-in-place and by the standalone per-pathway page (which used to render this same
    data as a hand-drawn SVG row diagram)."""
    reaction_nodes = []
    metabolite_by_id = {}
    participants = []

    for reaction in reactions:
        reaction_nodes.append(_reaction_topology_row(reaction))
        for participant in reaction.participants.all():
            species = participant.species
            if species.species_id not in metabolite_by_id:
                metabolite_by_id[species.species_id] = {
                    "id": species.species_id,
                    "name": species.display_name or species.species_id,
                    "compartment": species.compartment or "",
                    "is_currency": species.is_currency,
                }
            participants.append(
                {
                    "reaction_id": reaction.reaction_id,
                    "species_id": species.species_id,
                    "role": participant.role,
                    "stoichiometry": participant.stoichiometry,
                }
            )

    return {
        "reactions": reaction_nodes,
        "metabolites": list(metabolite_by_id.values()),
        "participants": participants,
    }


class MetabolismNetworkExpandView(View):
    """JSON: one pathway's reactions + metabolites + substrate/product links, fetched when
    the user clicks a collapsed pathway node to expand it in place. Uses the exact same
    _primary_pathway_buckets partition as MetabolismNetworkGraphView, so a node's promised
    reaction_count always matches what expanding it reveals."""

    def get(self, request, genome, source, external_id, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")
        source = source.upper()

        buckets = _primary_pathway_buckets(assembly_name)
        reaction_ids = {
            rid for rid, key in buckets.items() if key[0] == source and key[1] == external_id
        }
        if not reaction_ids:
            raise Http404("Pathway not found for this genome")

        reactions = MetabolicReaction.objects.filter(id__in=reaction_ids).prefetch_related(
            "genes__bioentry",
            "participants__species",
        )
        payload = _reaction_metabolite_graph(reactions)
        return JsonResponse(payload)

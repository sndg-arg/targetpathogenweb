from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Metabolism import GeneReactionLink, MetabolicPathway, MetabolicReaction
from tpweb.services.genome_workspace import display_genome_name, genome_url_slug, resolve_genome_from_slug
from tpweb.services.metabolism_summary import build_genome_metabolism_summary


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
        summary = build_genome_metabolism_summary(assembly_name, user=request.user, formula_name=formula_name)
        return render(request, self.template_name, {
            "assembly": {
                "name": display_genome_name(assembly_name),
                "internal_name": assembly_name,
                "slug": slug,
                "description": biodb.description,
            },
            "summary": summary,
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
            "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
        })


def _participant_payload(participants, role):
    rows = []
    for participant in participants:
        if participant.role != role:
            continue
        species = participant.species
        rows.append({
            "name": species.display_name or species.species_id,
            "species_id": species.species_id,
            "compartment": species.compartment or "model",
            "is_currency": species.is_currency,
            "stoichiometry": participant.stoichiometry,
        })
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
        (link.chokepoint_role for link in links if link.chokepoint_role != GeneReactionLink.CHOKEPOINT_NONE),
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
        "kegg_url": f"https://www.kegg.jp/entry/{reaction.kegg_reaction_id}" if reaction.kegg_reaction_id else "",
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
            reactions_qs
            .distinct()
            .prefetch_related("participants__species", "genes__bioentry")
            .order_by("reaction_id")
        )
        if not reactions:
            raise Http404("Pathway not found for this genome")

        reaction_rows = [_build_reaction_row(reaction) for reaction in reactions]
        protein_ids = {
            gene["protein_id"]
            for row in reaction_rows
            for gene in row["genes"]
        }
        metabolite_ids = {
            participant.species.species_id
            for reaction in reactions
            for participant in reaction.participants.all()
        }
        chokepoint_count = sum(1 for row in reaction_rows if row["is_chokepoint"])
        diagram_reactions = reaction_rows[:45]
        omitted_reactions = max(0, len(reaction_rows) - len(diagram_reactions))
        slug = genome_url_slug(assembly_name)

        return render(request, self.template_name, {
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
            "diagram_payload": {
                "pathway": pathway,
                "reactions": diagram_reactions,
                "omitted_reactions": omitted_reactions,
            },
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
            "metabolism_url": reverse("tpwebapp:genome_metabolism", kwargs={"genome": slug}),
            "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
        })

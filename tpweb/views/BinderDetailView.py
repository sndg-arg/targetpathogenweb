from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    user_can_access_genome_name,
)
from tpweb.views.ProteinView import make_binder_svg


class BinderDetailView(View):
    template_name = "genomic/binder.html"

    def get(self, request, binder_id, *args, **kwargs):
        try:
            binder = Binders.objects.select_related("locustag__biodatabase").get(pk=binder_id)
        except Binders.DoesNotExist:
            raise Http404("Binder not found")

        protein = binder.locustag
        biodb_name = protein.biodatabase.name
        prot_postfix = getattr(Biodatabase, "PROT_POSTFIX", "")
        if prot_postfix and biodb_name.endswith(prot_postfix):
            assembly_name = biodb_name[: -len(prot_postfix)]
        else:
            assembly_name = biodb_name

        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Binder not found")

        is_pdb = binder.source == Binders.SOURCE_PDB
        ctx = {
            "binder": {
                "id": binder.id,
                "name": binder.ccd_id or f"Binder {binder.id}",
                "ccd_id": binder.ccd_id,
                "pdb_id": binder.pdb_id,
                "uniprot": binder.uniprot,
                "smiles": binder.smiles,
                "source": binder.source,
                "source_label": binder.get_source_display(),
                "is_pdb": is_pdb,
                "is_proposed": binder.source == Binders.SOURCE_PROPOSED,
                "score": binder.score,
                "notes": binder.notes,
                "svg": make_binder_svg(binder.smiles) if is_pdb else "",
            },
            "protein": {
                "id": protein.bioentry_id,
                "accession": protein.accession,
                "description": protein.description,
            },
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "genome": genome_url_slug(assembly_name),
            "protein_url": reverse("tpwebapp:protein", kwargs={"protein_id": protein.bioentry_id}),
            "proteins_url": reverse(
                "tpwebapp:protein_list",
                kwargs={"genome": genome_url_slug(assembly_name)},
            ),
            "rcsb_ligand_url": (
                f"https://www.rcsb.org/ligand/{binder.ccd_id}" if is_pdb and binder.ccd_id else ""
            ),
            "rcsb_structure_url": (
                f"https://www.rcsb.org/structure/{binder.pdb_id}" if is_pdb and binder.pdb_id else ""
            ),
        }
        return render(request, self.template_name, ctx)

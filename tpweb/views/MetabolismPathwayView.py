from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
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
        summary = build_genome_metabolism_summary(assembly_name)
        return render(request, self.template_name, {
            "assembly": {
                "name": display_genome_name(assembly_name),
                "internal_name": assembly_name,
                "description": biodb.description,
            },
            "summary": summary,
            "assembly_url": reverse("tpwebapp:assembly", kwargs={"genome": slug}),
            "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
        })

from django.shortcuts import render
from django.http import Http404
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.Bioentry import Bioentry

from django.conf import settings
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
)
from tpweb.services.genome_workspace import (
    display_genome_name,
    user_can_access_genome_name,
)


class AssemblyView(View):
    template_name = 'genomic/assembly.html'

    def get(self, request, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        if not user_can_access_genome_name(request.user, kwargs["assembly_id"]):
            raise Http404("Genome not found")

        biodb = Biodatabase.objects.get(name=kwargs["assembly_id"])

        props = {bqv.term.identifier: bqv.value
                 for bqv in BiodatabaseQualifierValue.objects.filter(biodatabase=biodb)}
        config_lt = Bioentry.objects.filter(biodatabase=biodb).first().accession
        assembly = {
            "id": biodb.biodatabase_id,
            "name": display_genome_name(biodb.name),
            "internal_name": biodb.name,
            "description": biodb.description,
            "props": props
        }

        jbrowse_url = f"{settings.JBROWSE_BASE_URL}?config=data/jbrowse/{biodb.name}/config.json&loc={ config_lt}:1..15000&assembly=Ref&tracks=Ref-ReferenceSequenceTrack,Annotation"
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), biodb.name
        )
        return render(
            request,
            self.template_name,
            {
                "assembly": assembly,
                "jbrowse_url": jbrowse_url,
                "pipeline_status": pipeline_status,
            },
        )  # , {'form': form})

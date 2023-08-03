from django.shortcuts import render
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.Bioentry import Bioentry

from django.conf import settings


class AssemblyView(View):
    template_name = 'genomic/assembly.html'

    def get(self, request, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        biodb = Biodatabase.objects.get(name=kwargs["assembly_id"])

        props = {bqv.term.identifier: bqv.value
                 for bqv in BiodatabaseQualifierValue.objects.filter(biodatabase=biodb)}
        config_lt = Bioentry.objects.filter(biodatabase=biodb).first().accession
        assembly = {
            "id": biodb.biodatabase_id,
            "name": biodb.name,
            "description": biodb.description,
            "props": props
        }

        jbrowse_url = f"{settings.JBROWSE_BASE_URL}?config=data/jbrowse/{biodb.name}/config.json&loc={ config_lt}:1..15000&assembly=Ref&tracks=Ref-ReferenceSequenceTrack,Annotation"
        return render(request, self.template_name,
                      {"assembly": assembly, "jbrowse_url": jbrowse_url})  # , {'form': form})

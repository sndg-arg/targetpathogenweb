from django.shortcuts import render
from django.views import View
from django.http import Http404
import urllib.parse


from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.Bioentry import Bioentry
from bioseq.io.SeqStore import SeqStore
from django.conf import settings


class AssemblyView(View):
    template_name = 'genomic/assembly.html'

    def get(self, request, *args, **kwargs):
        try:
            biodb = Biodatabase.objects.get(name=kwargs["assembly_id"])
        except Biodatabase.DoesNotExist:
            raise Http404("Biodatabase does not exist")

        props = {bqv.term.identifier: bqv.value
                 for bqv in BiodatabaseQualifierValue.objects.filter(biodatabase=biodb)}
        config_lt = Bioentry.objects.filter(biodatabase=biodb).first()
        if not config_lt:
            raise Http404("No Bioentry found for the Biodatabase")
        config_lt = config_lt.accession

        assembly = {
            "id": biodb.biodatabase_id,
            "name": biodb.name,
            "description": biodb.description,
            "props": props
        }

        
        seq_store = SeqStore(settings.JBROWSE_DATA_DIR)
        config_path = seq_store.db_dir(biodb.name)
        config_path = "/data" + config_path.replace(settings.JBROWSE_DATA_DIR, "")
        config_path = urllib.parse.quote(config_path, safe='/')
        print("Encoded config path:", config_path)

        jbrowse_url = f"{settings.JBROWSE_BASE_URL}?config={config_path}/config.json"

        return render(request, self.template_name, {"assembly": assembly, "jbrowse_url": jbrowse_url})

        '''jbrowse_url = f"{settings.JBROWSE_BASE_URL}?config=data/asdasd/{biodb.name}/config.json&loc={config_lt}:1..15000&assembly=Ref&tracks=Ref-ReferenceSequenceTrack,Annotation"'''
        '''jbrowse_url = "http://localhost:3000/?config=%2Fdata%2F009%2FNC_000962.3%2Fconfig.json"'''
        '''return render(request, self.template_name, {"assembly": assembly, "jbrowse_url": jbrowse_url})'''

from django.views import View
from django.conf import settings
from django.http import Http404

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from tpweb.models.pdb import PDB

import gzip
from tpweb.services.genome_workspace import user_can_access_genome_name

class StructureRawView(View):
    template_name = 'genomic/protein.html'

    def get(self, request, struct_id, *args, **kwargs):
        pdbqs = PDB.objects.filter(id=struct_id)

        if pdbqs.exists():
            pdb = pdbqs.get()
            be = pdb.sequences.all()[0].bioentry
            biodb = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
            if not user_can_access_genome_name(request.user, biodb):
                raise Http404("Structure not found")
            ss = SeqStore(settings.SEQS_DATA_DIR)
            data = gzip.open(ss.structure(biodb, be.accession, pdb.code),"rt").read()
            # open(ss.structure(biodb, be.accession, pdb.code),"rb")
            response = HttpResponse(data,
                                content_type="text/plain; charset=utf-8")
            #response['Content-Encoding'] = 'gzip'
            return response
        else:
            return HttpResponseNotFound()


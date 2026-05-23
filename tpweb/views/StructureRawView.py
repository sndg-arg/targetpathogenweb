from django.views import View
from django.http import Http404

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from tpweb.models.pdb import PDB

import gzip
from tpweb.services.genome_workspace import user_can_access_genome_name
from tpweb.services.structure_files import structure_file_path

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
            try:
                raw_structure_path = structure_file_path(biodb, be.accession, pdb.code)
                data = gzip.open(raw_structure_path, "rt").read()
            except (FileNotFoundError, OSError):
                return HttpResponseNotFound("Structure source file not found.")
            response = HttpResponse(data,
                                content_type="text/plain; charset=utf-8")
            #response['Content-Encoding'] = 'gzip'
            return response
        else:
            return HttpResponseNotFound()

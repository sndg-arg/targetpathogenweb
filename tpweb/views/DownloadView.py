import os.path

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.utils.encoding import smart_str
from django.views import View

from bioseq.io.SeqStore import SeqStore
from tpweb.services.genome_workspace import resolve_genome_from_slug


class DownloadView(View):

    def get(self, request, *args, **kwargs):
        allowed_formats = {"genome", "genes", "proteins", "gff", "gbk"}
        if "accession" not in request.GET:
            return HttpResponseBadRequest("no accession provided...")
        if "format" not in request.GET:
            return HttpResponseBadRequest("no format provided...")
        if request.GET["format"] not in allowed_formats:
            return HttpResponseBadRequest("invalid format")

        internal_accession = resolve_genome_from_slug(request.user, request.GET["accession"])
        if not internal_accession:
            raise Http404("Genome not found")

        ss = SeqStore(settings.SEQS_DATA_DIR)
        paths = {
            "genome": ss.genome_fna(internal_accession),
            "genes": ss.genes_fna(internal_accession),
            "proteins": ss.faa(internal_accession),
            "gff": ss.gff(internal_accession),
            "gbk": ss.gbk(internal_accession),
        }

        path_to_file = paths[request.GET["format"]]
        if not os.path.exists(path_to_file):
            return HttpResponseNotFound(f'Accession: "{request.GET["accession"]}" does not exist')

        response = HttpResponse(open(path_to_file, "rb"), content_type="application/force-download")
        response["Content-Disposition"] = "attachment; filename=%s" % smart_str(os.path.basename(path_to_file))
        response["X-Sendfile"] = smart_str(path_to_file)
        return response

    def post(self, request, *args, **kwargs):
        return self.get(request, args, kwargs)

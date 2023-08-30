import os.path

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.utils.encoding import smart_str
from django.views import View

from bioseq.io.SeqStore import SeqStore
from django.conf import settings


class DownloadView(View):

    def get(self, request, *args, **kwargs):

        formats = {"genome", "genes", "proteins", "gff", "gbk"}
        if 'accession' not in request.GET:
            return HttpResponseBadRequest('no accession provided...')
        if 'format' not in request.GET:
            return HttpResponseBadRequest('no accession provided...')
        elif request.GET['format'] not in formats:
            return HttpResponseBadRequest('invalid format')

        accession = request.GET['accession']
        fformat = request.GET["format"]

        ss = SeqStore(settings.SEQS_DATA_DIR)
        formats = {"genome": ss.genome_fna(accession), "genes": ss.genes_fna(accession), "proteins": ss.faa(accession),
                   "gff": ss.gff(accession), "gbk": ss.gbk(accession)}

        if not os.path.exists(ss.gbk(accession)):
            return HttpResponseNotFound(f'Accession: "{accession}"  does not exists')

        path_to_file = formats[fformat]
        response = HttpResponse(open(path_to_file, 'rb'), content_type='application/force-download')
        response['Content-Disposition'] = 'attachment; filename=%s' % smart_str(os.path.basename(path_to_file))
        response['X-Sendfile'] = smart_str(path_to_file)
        return response

    def post(self, request, *args, **kwargs):
        return self.get(request, args, kwargs)

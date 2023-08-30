from django.views import View
from django.shortcuts import render

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


class ProteinListView(View):
    template_name = 'search/proteins.html'
    tcolumns = ["Length", "PW", "Druggability"]

    def get(self, request, assembly_id, *args, **kwargs):
        tdatas = {}
        page = request.GET.get('page', 1)
        pageSize = request.GET.get('pageSize', 10)

        proteins = Bioentry.objects.filter(
            biodatabase__name=assembly_id + Biodatabase.PROT_POSTFIX,
            structures__isnull=False
        ).prefetch_related("qualifiers__term","dbxrefs__dbxref")

        paginator = Paginator(proteins, pageSize)

        try:
            proteins = paginator.page(page)
        except PageNotAnInteger:
            proteins = paginator.page(1)
        except EmptyPage:
            proteins = paginator.page(paginator.num_pages)

        proteins_dto = []
        for protein in proteins:
            protein_dto = {
                "id": protein.bioentry_id,
                "accession": protein.accession,
                "genes": protein.genes(),
                "name": protein.name,
                "description": protein.description
            }
            """
            qvs = genome.qualifiers_dict()
            for qname in GenomesView.tcolumns:
                if qname in qvs:
                    genome_dto[qname] = qvs[qname]
            
            """
            tdata = {"Length":protein.seq.length,

                     }
            tdatas[protein.bioentry_id] = tdata

            proteins_dto.append(protein_dto)

        return render(request, self.template_name, {"proteins": proteins_dto,
                                                    "tcolumns": ProteinListView.tcolumns,
                                                    "tdata":tdatas})  # , {'form': form})

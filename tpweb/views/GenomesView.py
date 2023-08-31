from django.shortcuts import render
from django.views import View
from django.db.models import Q
from bioseq.models.Biodatabase import Biodatabase


class GenomesView(View):
    template_name = 'search/genomes.html'
    tcolumns = {"EntryLength":"Length [bp]",
                "COUNT_CDS":"# Proteins",
                "COUNT_STRUCTS": "# Structures"} #["EntryLength", "GC", "COUNT_gene", "COUNT_pathways", "COUNT_structures"]

    def get(self, request, *args, **kwargs):

        genomes = Biodatabase.objects.exclude(Q(name__endswith='_rnas') | Q(name__endswith='_prots')
                                              ).prefetch_related("qualifiers__term")

        genomes_dto = []
        for genome in genomes:
            genome_dto = {

                "name": genome.name,
                "description": genome.description
            }
            qvs = genome.qualifiers_dict()
            for qname in GenomesView.tcolumns:
                if qname in qvs:
                    genome_dto[qname] = qvs[qname]
            genomes_dto.append(genome_dto)

        return render(request, self.template_name, {"genomes": genomes_dto,
                                                    "tcolumns": GenomesView.tcolumns})  # , {'form': form})

from django.shortcuts import render
from django.views import View
from tpweb.services.genomes import (
    GENOME_TABLE_COLUMNS,
    build_genomes_dto,
    build_genomes_queryset,
    summarize_genomes,
)
from tpweb.services.pipeline_status import get_pipeline_status



class GenomesView(View):
    template_name = 'search/genomes.html'
    tcolumns = GENOME_TABLE_COLUMNS

    def get(self, request, *args, **kwargs):

        search_query = request.GET.get('search', '').strip()
        genomes = build_genomes_queryset(search_query=search_query)
        genomes_dto = build_genomes_dto(genomes, columns=GenomesView.tcolumns)
        genome_metrics = summarize_genomes(genomes_dto)
        selected_genome = genomes_dto[0] if genomes_dto else None
        show_detail_panel = genome_metrics["total_genomes"] > 1

        return render(
            request,
            self.template_name,
            {
                "genomes": genomes_dto,
                "tcolumns": GenomesView.tcolumns,
                "search_query": search_query,
                "total_genomes": genome_metrics["total_genomes"],
                "total_proteins": genome_metrics["total_proteins"],
                "total_structures": genome_metrics["total_structures"],
                "genomes_with_structures": genome_metrics["genomes_with_structures"],
                "selected_genome": selected_genome,
                "show_detail_panel": show_detail_panel,
                "pipeline_status": get_pipeline_status(),
            },
        )  # , {'form': form})

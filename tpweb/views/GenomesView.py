from django.shortcuts import render
from django.views import View
from tpweb.services.genomes import (
    GENOME_TABLE_COLUMNS,
    build_genomes_dto,
    build_genomes_queryset,
    summarize_genomes,
)
from tpweb.services.pipeline_status import get_pipeline_status, sanitize_pipeline_status_for_user



class GenomesView(View):
    template_name = 'search/genomes.html'
    tcolumns = GENOME_TABLE_COLUMNS

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('search', '').strip()
        has_search = bool(search_query)
        genomes = build_genomes_queryset(user=request.user, search_query=search_query)
        genomes_dto = build_genomes_dto(genomes, columns=GenomesView.tcolumns)
        genome_metrics = summarize_genomes(genomes_dto)

        return render(
            request,
            self.template_name,
            {
                "genomes": genomes_dto,
                "tcolumns": GenomesView.tcolumns,
                "search_query": search_query,
                "has_search": has_search,
                "total_genomes": genome_metrics["total_genomes"],
                "total_proteins": genome_metrics["total_proteins"],
                "total_structures": genome_metrics["total_structures"],
                "genomes_with_structures": genome_metrics["genomes_with_structures"],
                "pipeline_status": sanitize_pipeline_status_for_user(
                    get_pipeline_status(), request.user
                ),
            },
        )  # , {'form': form})

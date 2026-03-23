from django.shortcuts import render
from django.views import View
from tpweb.services.genomes import (
    GENOME_TABLE_COLUMNS,
    build_genomes_dto,
    build_genomes_queryset,
    summarize_genomes,
)
from tpweb.services.csv_exports import csv_response, xlsx_sections_response
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genomes,
    get_pipeline_status,
    sanitize_pipeline_status_for_user,
)



class GenomesView(View):
    template_name = 'search/genomes.html'
    tcolumns = GENOME_TABLE_COLUMNS

    @staticmethod
    def _build_export_url(request):
        params = request.GET.copy()
        params["export"] = "csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=csv"

    @staticmethod
    def _build_view_export_url(request):
        params = request.GET.copy()
        params["export"] = "view_csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=view_csv"

    def get(self, request, *args, **kwargs):
        search_query = request.GET.get('search', '').strip()
        has_search = bool(search_query)
        genomes = build_genomes_queryset(user=request.user, search_query=search_query)
        genomes_dto = build_genomes_dto(
            genomes,
            user=request.user,
            columns=GenomesView.tcolumns,
        )
        pipeline_status = sanitize_pipeline_status_for_user(
            get_pipeline_status(), request.user
        )
        genomes_dto = annotate_pipeline_status_for_genomes(genomes_dto, pipeline_status)
        genome_metrics = summarize_genomes(genomes_dto)

        export_mode = request.GET.get("export")
        if export_mode in {"csv", "view_csv"}:
            headers = ["Name", "Scope", "Description", *GenomesView.tcolumns.values()]
            rows = [
                [
                    genome["name"],
                    genome["workspace_scope_label"],
                    genome["description"],
                    *[genome.get(column, "-") for column in GenomesView.tcolumns],
                ]
                for genome in genomes_dto
            ]
            if export_mode == "view_csv":
                sections = [
                    {
                        "title": "Current view",
                        "headers": ["Field", "Value"],
                        "rows": [
                            ["Search query", search_query or "-"],
                            ["Visible genomes", genome_metrics["total_genomes"]],
                            ["Visible proteins", genome_metrics["total_proteins"]],
                            ["Experimental structures", genome_metrics["total_experimental"]],
                            ["EC annotated", genome_metrics["total_ec_annotated"]],
                            ["Visible columns", ", ".join(["Name", "Scope", "Description", *GenomesView.tcolumns.values()])],
                        ],
                    },
                    {
                        "title": "Genome table",
                        "headers": headers,
                        "rows": rows,
                    },
                ]
                return xlsx_sections_response("genomes-view", sections)
            return csv_response("genomes", headers, rows)

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
                "total_experimental": genome_metrics["total_experimental"],
                "total_ec_annotated": genome_metrics["total_ec_annotated"],
                "pipeline_status": pipeline_status,
                "workspace_deleted": request.GET.get("workspace_deleted", "").strip(),
                "export_url": self._build_export_url(request),
                "view_export_url": self._build_view_export_url(request),
            },
        )  # , {'form': form})

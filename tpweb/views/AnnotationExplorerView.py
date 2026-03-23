from django.http import Http404
from django.shortcuts import render
from django.views import View

from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.csv_exports import csv_response, xlsx_sections_response
from tpweb.services.genome_workspace import display_genome_name, user_can_access_genome_name
from tpweb.services.pipeline_status import annotate_pipeline_status_for_genome, get_pipeline_status
from tpweb.services.protein_annotations import build_annotation_explorer, normalize_annotation_kind


class AnnotationExplorerView(View):
    template_name = "genomic/annotation_explorer.html"

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

    def get(self, request, assembly_name, annotation_kind, *args, **kwargs):
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Genome not found")

        normalized_kind = normalize_annotation_kind(annotation_kind)
        proteins = (
            Bioentry.objects.filter(
                biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX
            )
            .prefetch_related("dbxrefs__dbxref__terms")
            .order_by("accession")
        )

        explorer = build_annotation_explorer(proteins, normalized_kind)
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), assembly_name
        )

        export_headers = ["Annotation", "Name", "Proteins"]
        export_rows = [
            [row["accession"], row.get("name", ""), row["protein_count"]]
            for row in explorer["rows"]
        ]
        export_mode = request.GET.get("export")
        if export_mode == "csv":
            return csv_response(
                f"{display_genome_name(assembly_name)}-{explorer['kind']}-annotations",
                export_headers,
                export_rows,
            )
        if export_mode == "view_csv":
            sections = [
                {
                    "title": "Current view",
                    "headers": ["Field", "Value"],
                    "rows": [
                        ["Genome accession", display_genome_name(assembly_name)],
                        ["Explorer", f"{explorer['kind_label']} Explorer"],
                        ["Annotations", explorer["annotation_count"]],
                        ["Hierarchy nodes", explorer["node_count"]],
                        ["Visible columns", ", ".join(export_headers)],
                    ],
                },
                {
                    "title": "Annotation table",
                    "headers": export_headers,
                    "rows": export_rows,
                },
            ]
            return xlsx_sections_response(
                f"{display_genome_name(assembly_name)}-{explorer['kind']}-view",
                sections,
            )

        return render(
            request,
            self.template_name,
            {
                "assembly_name": assembly_name,
                "assembly_label": display_genome_name(assembly_name),
                "annotation_kind": normalized_kind,
                "explorer": explorer,
                "pipeline_status": pipeline_status,
                "export_url": self._build_export_url(request),
                "view_export_url": self._build_view_export_url(request),
            },
        )

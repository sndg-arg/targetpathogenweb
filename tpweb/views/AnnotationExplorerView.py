from django.core.cache import cache
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import render
from django.views import View

from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.csv_exports import (
    build_export_url,
    build_view_export_url,
    csv_response,
    xlsx_sections_response,
)
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
)
from tpweb.services.pipeline_status import annotate_pipeline_status_for_genome, get_pipeline_status
from tpweb.services.protein_annotations import (
    annotation_dbnames,
    build_annotation_explorer,
    normalize_annotation_kind,
)

EXPLORER_CACHE_TTL_SECONDS = 900


def _genome_explorer(assembly_name, kind):
    """The explorer for one genome and kind (EC/GO), cached like the other
    genome-scoped aggregates: annotations only change on a pipeline run.
    Only the EC/GO cross-references are loaded -- the page used to prefetch
    every cross-reference of every protein (UniProt, PDB, InterPro...), which
    made it take 25-35 s."""
    cache_key = f"Target:annotation_explorer:{assembly_name}:{kind}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    dbnames = annotation_dbnames(kind)
    proteins = (
        Bioentry.objects.filter(
            biodatabase__name=assembly_name + Biodatabase.PROT_POSTFIX,
            dbxrefs__dbxref__dbname__in=dbnames,
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "dbxrefs",
                queryset=BioentryDbxref.objects.filter(dbxref__dbname__in=dbnames)
                .select_related("dbxref")
                .prefetch_related("dbxref__terms__term"),
            )
        )
        .order_by("accession")
    )
    explorer = build_annotation_explorer(proteins, kind)
    cache.set(cache_key, explorer, EXPLORER_CACHE_TTL_SECONDS)
    return explorer


class AnnotationExplorerView(View):
    template_name = "genomic/annotation_explorer.html"

    def get(self, request, genome, annotation_kind, *args, **kwargs):
        assembly_name = resolve_genome_from_slug(request.user, genome)
        if not assembly_name:
            raise Http404("Genome not found")

        normalized_kind = normalize_annotation_kind(annotation_kind)
        explorer = _genome_explorer(assembly_name, normalized_kind)
        pipeline_status = annotate_pipeline_status_for_genome(get_pipeline_status(), assembly_name)

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
                "genome": genome_url_slug(assembly_name),
                "annotation_kind": normalized_kind,
                "explorer": explorer,
                "pipeline_status": pipeline_status,
                "export_url": build_export_url(request),
                "view_export_url": build_view_export_url(request),
            },
        )

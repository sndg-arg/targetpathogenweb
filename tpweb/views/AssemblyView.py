from urllib.parse import quote_plus
from urllib.parse import urlparse
from pathlib import Path

from django.shortcuts import redirect, render
from django.http import Http404
from django.views import View
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.Bioentry import Bioentry

from django.conf import settings
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
    sanitize_pipeline_status_for_user,
)
from tpweb.services.assembly_workspace import build_assembly_workspace_metrics
from tpweb.services.assembly_overview import build_assembly_overview
from tpweb.services.genome_metadata import build_genome_metadata_rows
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    resolve_genome_from_slug,
    user_can_delete_genome_name,
)
from tpweb.services.genome_uploads import delete_genome_workspace, workspace_has_active_upload
from tpweb.services.csv_exports import xlsx_sections_response


class AssemblyView(View):
    template_name = 'genomic/assembly.html'
    ACTION_DELETE_WORKSPACE = "delete_workspace"

    @staticmethod
    def _build_view_export_url(request):
        params = request.GET.copy()
        params["export"] = "view_csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=view_csv"

    def _resolve_jbrowse_base_url(self, request):
        configured = str(settings.JBROWSE_BASE_URL or "").strip()
        parsed = urlparse(configured)
        host = parsed.hostname or ""
        port = parsed.port or 3000
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return configured

        request_host = request.get_host().split(":")[0].strip()
        if request_host in {"", "localhost", "127.0.0.1", "0.0.0.0"}:
            return configured

        scheme = "https" if request.is_secure() else "http"
        return f"{scheme}://{request_host}:{port}/"

    def _get_biodatabase(self, request, genome_slug):
        internal_name = resolve_genome_from_slug(request.user, genome_slug)
        if not internal_name:
            raise Http404("Genome not found")
        try:
            return Biodatabase.objects.get(name=internal_name)
        except Biodatabase.DoesNotExist as exc:
            raise Http404("Genome not found") from exc

    def _build_context(self, request, biodb, error_message=""):
        props = {bqv.term.identifier: bqv.value
                 for bqv in BiodatabaseQualifierValue.objects.filter(biodatabase=biodb)}
        reference_entry = Bioentry.objects.filter(biodatabase=biodb).only("accession").first()
        reference_accession = str(getattr(reference_entry, "accession", "") or "").strip()
        assembly = {
            "id": biodb.biodatabase_id,
            "name": display_genome_name(biodb.name),
            "internal_name": biodb.name,
            "description": biodb.description,
            "props": props,
            "prop_rows": build_genome_metadata_rows(props),
        }
        workspace_metrics = build_assembly_workspace_metrics(biodb.name)
        overview = build_assembly_overview(
            request.user,
            biodb.name,
            biodb.description,
            props,
            workspace_metrics=workspace_metrics,
        )
        slug = genome_url_slug(biodb.name)
        workspace_links = {
            "proteins_url": reverse("tpwebapp:protein_list", kwargs={"genome": slug}),
            "custom_scores_url": reverse("tpwebapp:customparam", kwargs={"genome": slug}),
            "ec_explorer_url": reverse(
                "tpwebapp:annotation_explorer",
                kwargs={"genome": slug, "annotation_kind": "ec"},
            ),
            "blast_url": f"{reverse('tpwebapp:form')}?genome={biodb.name}",
        }

        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_absolute():
            media_root = Path(settings.BASE_DIR) / media_root
        jbrowse_config_path = media_root / "jbrowse" / biodb.name / "config.json"
        jbrowse_config_exists = jbrowse_config_path.exists()
        jbrowse_assembly_name = f"{biodb.name}.genome.fna.bgz"
        jbrowse_reference_track = f"{jbrowse_assembly_name}-ReferenceSequenceTrack"
        jbrowse_annotation_track = f"{biodb.name}.gff"
        jbrowse_base_url = self._resolve_jbrowse_base_url(request)
        jbrowse_url = (
            f"{jbrowse_base_url}"
            f"?config=data/jbrowse/{biodb.name}/config.json"
            f"&assembly={jbrowse_assembly_name}"
            f"&tracks={jbrowse_reference_track},{jbrowse_annotation_track}"
        )
        if reference_accession:
            jbrowse_url = f"{jbrowse_url}&loc={reference_accession}:1..15000"
        jbrowse_host = urlparse(jbrowse_base_url).hostname or ""
        jbrowse_embed = {
            "enabled": (
                bool(getattr(settings, "JBROWSE_EMBED_ENABLED", False))
                and jbrowse_config_exists
                and bool(reference_accession)
            ),
            "uses_local_service": jbrowse_host in {"localhost", "127.0.0.1", "0.0.0.0"},
            "config_exists": jbrowse_config_exists,
        }
        pipeline_status = annotate_pipeline_status_for_genome(
            sanitize_pipeline_status_for_user(get_pipeline_status(), request.user),
            biodb.name,
        )
        return {
            "assembly": assembly,
            "overview": overview,
            "workspace_metrics": workspace_metrics,
            "workspace_links": workspace_links,
            "view_export_url": self._build_view_export_url(request),
            "jbrowse_url": jbrowse_url,
            "jbrowse_embed": jbrowse_embed,
            "pipeline_status": pipeline_status,
            "can_delete_workspace": user_can_delete_genome_name(request.user, biodb.name),
            "delete_error_message": error_message,
        }

    def get(self, request, *args, **kwargs):
        biodb = self._get_biodatabase(request, kwargs["genome"])
        if request.GET.get("export") == "view_csv":
            context = self._build_context(request, biodb)
            assembly = context["assembly"]
            overview = context["overview"]
            workspace_metrics = context["workspace_metrics"]
            sections = [
                {
                    "title": "Genome overview",
                    "headers": ["Field", "Value"],
                    "rows": [
                        ["Genome", assembly["name"]],
                        ["Description", assembly["description"]],
                        ["Source", (overview.get("scope") or {}).get("label", "")],
                        ["Organism", next((fact["value"] for fact in overview.get("hero_facts", []) if fact.get("label") == "Organism"), "")],
                        ["Sequence length", next((fact["value"] for fact in overview.get("hero_facts", []) if fact.get("label") == "Sequence length"), "")],
                        ["Strain", overview.get("strain_display") or ""],
                        ["Record", overview.get("record_display") or ""],
                        ["Completion", overview.get("completion_display") or ""],
                        ["Annotated features", overview.get("feature_count_display") or ""],
                    ],
                },
                {
                    "title": "Genome composition",
                    "headers": ["Metric", "Value"],
                    "rows": [
                        ["Proteins available for analysis", workspace_metrics.get("total_proteins")],
                        [
                            "Structures loaded",
                            (
                                f"{workspace_metrics.get('proteins_with_structure')} total "
                                f"(Experimental {workspace_metrics.get('experimental_structures')}, "
                                f"AlphaFold {workspace_metrics.get('alphafold_structures')}, "
                                f"ColabFold {workspace_metrics.get('colabfold_structures')})"
                            ),
                        ],
                        [
                            "Functional annotation available",
                            f"{workspace_metrics.get('functional_annotated')} annotated proteins (EC {workspace_metrics.get('ec_annotated')}, GO {workspace_metrics.get('go_annotated')})",
                        ],
                        ["Annotated coding sequences", overview.get("source_cds_display") or ""],
                        ["Coding sequences without translated protein", overview.get("untranslated_cds_display") or ""],
                        ["RNA features", overview.get("rna_total_display") or ""],
                    ],
                },
                {
                    "title": "Imported genome details",
                    "headers": ["Property", "Value"],
                    "rows": [[row["label"], row["value"]] for row in assembly["prop_rows"]],
                },
            ]
            return xlsx_sections_response(f"{assembly['name']}-overview", sections)
        return render(request, self.template_name, self._build_context(request, biodb))

    def post(self, request, *args, **kwargs):
        biodb = self._get_biodatabase(request, kwargs["genome"])
        if request.POST.get("action") != self.ACTION_DELETE_WORKSPACE:
            raise Http404("Action not found")

        if not user_can_delete_genome_name(request.user, biodb.name):
            raise Http404("Genome not found")

        if workspace_has_active_upload(biodb.name, owner=request.user):
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    biodb,
                    error_message="This genome dataset still has a queued or running upload and cannot be deleted yet.",
                ),
            )

        expected_accession = display_genome_name(biodb.name)
        confirmation_value = str(request.POST.get("confirm_accession") or "").strip()
        if confirmation_value != expected_accession:
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    biodb,
                    error_message=f'Type "{expected_accession}" to confirm dataset deletion.',
                ),
            )

        delete_genome_workspace(biodb.name, owner=request.user)
        genomes_url = reverse("tpwebapp:genomes_list")
        return redirect(f"{genomes_url}?workspace_deleted={quote_plus(expected_accession)}")

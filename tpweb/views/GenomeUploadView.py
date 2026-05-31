from io import StringIO

from django.contrib import messages
from django.core.management import CommandError, call_command
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.forms.ExternalImportForm import ExternalImportForm
from tpweb.forms.GenomeUploadForm import GenomeUploadForm
from tpweb.models import GenomeUpload
from tpweb.services.genome_uploads import (
    TEST_GENOME_ACCESSION,
    build_queue_position_map,
    clear_genome_upload_history,
    owner_has_active_uploads,
)
from tpweb.services.genome_upload_status import (
    format_upload_timestamp,
    reconcile_genome_uploads,
)
from tpweb.services.genome_workspace import (
    build_workspace_genome_name,
    display_genome_name,
    genome_url_slug,
)
from tpweb.services.external_import import (
    build_external_import_command,
    validate_external_import,
)
from tpweb.services.pipeline_status import get_pipeline_status
from tpweb.services.pipeline_status import sanitize_pipeline_status_for_user
from tpweb.services.slurm_messages import classify_slurm_resource_message
from tpweb.services.workspace import resolve_workspace_user


class GenomeUploadView(View):
    template_name = "user/upload_data.html"
    ACTION_CLEAR_HISTORY = "clear_history"
    ACTION_USE_TEST_GENOME = "use_test_genome"
    ACTION_VALIDATE_EXTERNAL_IMPORT = "validate_external_import"
    ACTION_RUN_EXTERNAL_IMPORT = "run_external_import"
    ACTION_RUN_CURATED_FILE_PIPELINE = "run_curated_file_pipeline"

    @staticmethod
    def _job_state(job, pipeline_status, queue_positions, running_job_id=None):
        if (
            pipeline_status.get("running")
            and str(pipeline_status.get("genome_accession") or "").strip() == job.internal_accession
            and (running_job_id is None or job.id == running_job_id)
        ):
            return {"label": "Running", "class": "running"}
        if job.status == GenomeUpload.STATUS_SUBMITTED:
            queue_position = queue_positions.get(job.id)
            return {
                "label": f"Queued #{queue_position}" if queue_position else "Queued",
                "class": "queued",
            }
        return {"label": job.get_status_display(), "class": job.status}

    def _build_context(self, request, form=None, external_import_form=None, external_import_result=None):
        workspace_user = resolve_workspace_user(request.user)
        pipeline_status = sanitize_pipeline_status_for_user(get_pipeline_status(), request.user)
        reconcile_genome_uploads(pipeline_status, owner=workspace_user)
        queue_positions = build_queue_position_map()
        jobs = list(
            GenomeUpload.objects.filter(owner=workspace_user).order_by("-created_at", "-id")[:8]
        )

        # When the pipeline is active, only the most recently submitted job for
        # that accession is the real running one. Older jobs with the same
        # internal_accession must not be shown as running.
        running_job_id = None
        running_internal = str(pipeline_status.get("genome_accession") or "").strip()
        if pipeline_status.get("running") and running_internal:
            candidate = (
                GenomeUpload.objects.filter(internal_accession=running_internal)
                .order_by("-id")
                .values_list("id", flat=True)
                .first()
            )
            running_job_id = candidate

        jobs_dto = []
        for job in jobs:
            state = self._job_state(job, pipeline_status, queue_positions, running_job_id=running_job_id)
            assembly_url = ""
            if Biodatabase.objects.filter(name=job.internal_accession).exists():
                assembly_url = reverse(
                    "tpwebapp:assembly",
                    kwargs={"genome": genome_url_slug(job.internal_accession)},
                )
            jobs_dto.append(
                {
                    "id": job.id,
                    "display_accession": job.display_accession,
                    "internal_accession": job.internal_accession,
                    "assembly_url": assembly_url,
                    "gram": "Gram-negative" if job.gram == "n" else "Gram-positive",
                    "created_at": job.created_at,
                    "created_at_label": format_upload_timestamp(job.created_at),
                    "state_label": state["label"],
                    "state_class": state["class"],
                    "queue_position": queue_positions.get(job.id),
                    "protein_workspace_url": genome_url_slug(job.internal_accession),
                    "error_message": classify_slurm_resource_message(job.error_message)
                    or str(job.error_message or "").strip(),
                }
            )

        running_genome = pipeline_status.get("genome_display_accession") or pipeline_status.get(
            "genome_accession"
        )
        return {
            "form": form or GenomeUploadForm(),
            "external_import_form": external_import_form or ExternalImportForm(),
            "external_import_result": external_import_result,
            "jobs": jobs_dto,
            "test_genome_accession": TEST_GENOME_ACCESSION,
            "workspace_label": (
                workspace_user.username if request.user.is_authenticated else "public"
            ),
            "pipeline_status": pipeline_status,
            "has_active_jobs": owner_has_active_uploads(workspace_user),
            "running_genome_label": display_genome_name(running_genome),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._build_context(request))

    def post(self, request, *args, **kwargs):
        workspace_user = resolve_workspace_user(request.user)

        upload_url = reverse("tpwebapp:genome_upload")
        action = request.POST.get("action")

        if action in {
            self.ACTION_VALIDATE_EXTERNAL_IMPORT,
            self.ACTION_RUN_EXTERNAL_IMPORT,
            self.ACTION_RUN_CURATED_FILE_PIPELINE,
        }:
            if not request.user.is_staff:
                messages.error(request, "Staff access is required for curated external imports.")
                return redirect(upload_url)

            external_form = ExternalImportForm(request.POST)
            if not external_form.is_valid():
                return render(
                    request,
                    self.template_name,
                    self._build_context(
                        request,
                        external_import_form=external_form,
                        external_import_result={
                            "status": "error",
                            "message": "Review the highlighted fields.",
                        },
                    ),
                )

            cleaned = external_form.cleaned_data
            command = build_external_import_command(
                cleaned["genome_name"],
                cleaned["results_tsv"],
                structures_dir=cleaned.get("structures_dir") or "",
                datadir=cleaned["datadir"],
                overwrite=cleaned["overwrite"],
                ligq_output_dir=cleaned.get("ligq_output_dir") or "",
                load_ligq_output=cleaned.get("load_ligq_output") and action == self.ACTION_RUN_CURATED_FILE_PIPELINE,
                include_plan=action == self.ACTION_RUN_CURATED_FILE_PIPELINE,
            )
            try:
                summary = validate_external_import(
                    cleaned["genome_name"],
                    cleaned["results_tsv"],
                    structures_dir=cleaned.get("structures_dir") or "",
                    datadir=cleaned["datadir"],
                    ligq_output_dir=cleaned.get("ligq_output_dir") or "",
                )
            except CommandError as exc:
                return render(
                    request,
                    self.template_name,
                    self._build_context(
                        request,
                        external_import_form=external_form,
                        external_import_result={
                            "status": "error",
                            "message": str(exc),
                            "command": command,
                        },
                    ),
                )

            result = {
                "status": "ok",
                "summary": summary,
                "command": command,
            }

            if action in {self.ACTION_RUN_EXTERNAL_IMPORT, self.ACTION_RUN_CURATED_FILE_PIPELINE}:
                stdout = StringIO()
                stderr = StringIO()
                try:
                    call_command(
                        "import_external_results",
                        cleaned["genome_name"],
                        results_tsv=cleaned["results_tsv"],
                        structures_dir=cleaned.get("structures_dir") or None,
                        datadir=cleaned["datadir"],
                        overwrite=cleaned["overwrite"],
                        stdout=stdout,
                        stderr=stderr,
                    )
                    ligq_output_dir = cleaned.get("ligq_output_dir") or ""
                    should_load_ligq = (
                        action == self.ACTION_RUN_CURATED_FILE_PIPELINE
                        and cleaned.get("load_ligq_output")
                        and ligq_output_dir
                    )
                    if should_load_ligq:
                        ligq_summary = (summary or {}).get("ligq_output") or {}
                        if not ligq_summary.get("exists"):
                            raise CommandError(f"LigQ_2 output directory not found: {ligq_output_dir}")
                        call_command(
                            "load_ligq_2_results",
                            ligq_output_dir,
                            stdout=stdout,
                            stderr=stderr,
                        )
                    if action == self.ACTION_RUN_CURATED_FILE_PIPELINE:
                        call_command(
                            "curated_pipeline_plan",
                            cleaned["genome_name"],
                            results_tsv=cleaned["results_tsv"],
                            datadir=cleaned["datadir"],
                            stdout=stdout,
                            stderr=stderr,
                        )
                except Exception as exc:
                    result.update(
                        {
                            "status": "error",
                            "message": str(exc),
                            "stdout": stdout.getvalue(),
                            "stderr": stderr.getvalue(),
                        }
                    )
                else:
                    message = (
                        "Curated file pipeline completed."
                        if action == self.ACTION_RUN_CURATED_FILE_PIPELINE
                        else "Curated external import completed."
                    )
                    result.update(
                        {
                            "status": "imported",
                            "message": message,
                            "stdout": stdout.getvalue(),
                            "stderr": stderr.getvalue(),
                        }
                    )

            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    external_import_form=external_form,
                    external_import_result=result,
                ),
            )

        if action == self.ACTION_CLEAR_HISTORY:
            if owner_has_active_uploads(workspace_user):
                messages.error(
                    request,
                    "Remove or finish queued/running uploads before clearing this history.",
                )
                return redirect(upload_url)

            deleted_count = clear_genome_upload_history(workspace_user)
            if deleted_count:
                messages.success(request, "Genome upload history was cleared.")
            else:
                messages.info(request, "There was no genome upload history to clear.")
            return redirect(upload_url)

        if action == self.ACTION_USE_TEST_GENOME:
            internal_accession = build_workspace_genome_name(TEST_GENOME_ACCESSION, request.user)

            if Biodatabase.objects.filter(name=internal_accession).exists():
                messages.info(
                    request,
                    f"Genome {TEST_GENOME_ACCESSION} has already been processed.",
                )
                return redirect(upload_url)

            with transaction.atomic():
                if GenomeUpload.objects.select_for_update().filter(
                    owner=workspace_user,
                    internal_accession=internal_accession,
                    status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
                ).exists():
                    messages.error(
                        request,
                        f"Genome {TEST_GENOME_ACCESSION} is already queued or running for this account.",
                    )
                    return redirect(upload_url)

                GenomeUpload.objects.create(
                    owner=workspace_user,
                    display_accession=TEST_GENOME_ACCESSION,
                    internal_accession=internal_accession,
                    gram="n",
                    gbk_file="",
                    status=GenomeUpload.STATUS_SUBMITTED,
                )
            messages.success(request, f"Test genome {TEST_GENOME_ACCESSION} was added to the queue.")
            return redirect(upload_url)

        form = GenomeUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, self._build_context(request, form=form))

        display_accession = form.cleaned_data["accession"]
        internal_accession = build_workspace_genome_name(display_accession, request.user)

        if Biodatabase.objects.filter(name=internal_accession).exists():
            messages.info(
                request,
                f"Genome {display_accession} has already been processed.",
            )
            return redirect(upload_url)

        with transaction.atomic():
            if GenomeUpload.objects.select_for_update().filter(
                owner=workspace_user,
                internal_accession=internal_accession,
                status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
            ).exists():
                messages.error(
                    request,
                    f"Genome {display_accession} is already queued or running for this account.",
                )
                return redirect(upload_url)

            GenomeUpload.objects.create(
                owner=workspace_user,
                display_accession=display_accession,
                internal_accession=internal_accession,
                gram=form.cleaned_data["gram"],
                gbk_file=form.cleaned_data["gbk_file"],
                status=GenomeUpload.STATUS_SUBMITTED,
            )
        messages.success(request, f"Genome {display_accession} was added to the queue.")
        return redirect(upload_url)

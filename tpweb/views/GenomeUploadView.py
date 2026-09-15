from io import StringIO

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.management import CommandError, call_command
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.forms.ExternalImportForm import ExternalImportForm
from tpweb.forms.GenomeUploadForm import GenomeUploadForm
from tpweb.models import CuratedImportJob, GenomeUpload
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
    WORKSPACE_GENOME_DELIMITER,
    build_workspace_genome_name,
    display_genome_name,
    genome_url_slug,
)
from tpweb.services.curated_import_jobs import (
    create_curated_import_job,
    run_curated_import_job,
)
from tpweb.services.external_import import (
    build_external_import_command,
    validate_external_import,
)
from tpweb.services.pipeline_status import get_pipeline_status
from tpweb.services.pipeline_status import sanitize_pipeline_status_for_user
from tpweb.services.slurm_messages import classify_slurm_resource_message
from tpweb.services.workspace import (
    PUBLIC_WORKSPACE_USERNAME,
    get_public_workspace_user,
    resolve_workspace_user,
)


class GenomeUploadView(LoginRequiredMixin, View):
    template_name = "user/upload_data.html"
    ACTION_CLEAR_HISTORY = "clear_history"
    ACTION_CLEAR_FAILED_HISTORY = "clear_failed_history"
    ACTION_USE_TEST_GENOME = "use_test_genome"
    ACTION_VALIDATE_EXTERNAL_IMPORT = "validate_external_import"
    ACTION_RUN_EXTERNAL_IMPORT = "run_external_import"
    ACTION_RUN_CURATED_FILE_PIPELINE = "run_curated_file_pipeline"
    ACTION_RETRY_CURATED_IMPORT = "retry_curated_import"

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

    @staticmethod
    def _curated_job_dto(job):
        return {
            "id": job.id,
            "genome_name": job.genome_name,
            "status": job.status,
            "status_label": job.get_status_display(),
            "phase": job.phase,
            "created_at_label": format_upload_timestamp(job.created_at),
            "finished_at_label": format_upload_timestamp(job.finished_at)
            if job.finished_at
            else "",
            "command": job.command,
            "report_path": job.report_path,
            "error_message": str(job.error_message or "").strip(),
            "can_retry": job.can_retry,
        }

    def _curated_import_result(self, job, *, summary=None, command=None):
        message = {
            CuratedImportJob.STATUS_VALIDATED: "Curated import validation was saved.",
            CuratedImportJob.STATUS_RUNNING: "Curated import is running.",
            CuratedImportJob.STATUS_FINISHED: "Curated file pipeline completed.",
            CuratedImportJob.STATUS_FAILED: job.error_message or "Curated file pipeline failed.",
        }.get(job.status, "Curated import job updated.")
        status = "ok"
        if job.status == CuratedImportJob.STATUS_FINISHED:
            status = "imported"
        elif job.status == CuratedImportJob.STATUS_FAILED:
            status = "error"

        return {
            "status": status,
            "message": message,
            "summary": summary if summary is not None else job.summary_json,
            "command": command or job.command,
            "stdout": job.stdout,
            "stderr": job.stderr,
            "job": self._curated_job_dto(job),
        }

    def _build_context(
        self, request, form=None, external_import_form=None, external_import_result=None
    ):
        workspace_user = resolve_workspace_user(request.user)
        pipeline_status = sanitize_pipeline_status_for_user(get_pipeline_status(), request.user)
        reconcile_genome_uploads(pipeline_status, owner=workspace_user)
        if request.user.is_superuser:
            # Also sync status for any upload this superuser tagged to the
            # public workspace -- reconcile_genome_uploads only touches rows
            # owned by whoever it's called with, so a public-scoped upload
            # would otherwise never move past "Queued" in this superuser's
            # own view even once it's actually running or finished.
            reconcile_genome_uploads(pipeline_status, owner=get_public_workspace_user())
        queue_positions = build_queue_position_map()
        # A superuser can tag an upload to the public workspace instead of
        # their own (the "Make this genome public" checkbox below) -- without
        # this, that upload would be correctly queued and processed (the
        # worker dequeues globally, not per-owner) but silently invisible in
        # this superuser's own history list, since its owner is the shared
        # public user, not them.
        jobs_owner_filter = Q(owner=workspace_user)
        if request.user.is_superuser:
            jobs_owner_filter |= Q(owner=get_public_workspace_user())
        jobs = list(
            GenomeUpload.objects.filter(jobs_owner_filter).order_by("-created_at", "-id")[:8]
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
            state = self._job_state(
                job, pipeline_status, queue_positions, running_job_id=running_job_id
            )
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

        has_failed_jobs = any(job["state_class"] == "failed" for job in jobs_dto)

        curated_import_jobs = []
        if request.user.has_perm("tpweb.can_curated_import"):
            curated_import_jobs = [
                self._curated_job_dto(job)
                for job in CuratedImportJob.objects.filter(owner=workspace_user)[:8]
            ]
        running_genome = pipeline_status.get("genome_display_accession") or pipeline_status.get(
            "genome_accession"
        )
        return {
            "form": form or GenomeUploadForm(),
            "external_import_form": external_import_form or ExternalImportForm(),
            "external_import_result": external_import_result,
            "curated_import_jobs": curated_import_jobs,
            "jobs": jobs_dto,
            "test_genome_accession": TEST_GENOME_ACCESSION,
            "workspace_label": (
                workspace_user.username if request.user.is_authenticated else "public"
            ),
            "pipeline_status": pipeline_status,
            "has_active_jobs": owner_has_active_uploads(workspace_user)
            or (
                request.user.is_superuser and owner_has_active_uploads(get_public_workspace_user())
            ),
            "has_failed_jobs": has_failed_jobs,
            "running_genome_label": display_genome_name(running_genome),
            "can_upload_genome": request.user.has_perm("tpweb.can_upload_genome"),
            "can_make_public": request.user.is_superuser,
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._build_context(request))

    def post(self, request, *args, **kwargs):
        workspace_user = resolve_workspace_user(request.user)

        upload_url = reverse("tpwebapp:genome_upload")
        action = request.POST.get("action")

        if action == self.ACTION_RETRY_CURATED_IMPORT:
            if not request.user.has_perm("tpweb.can_curated_import"):
                messages.error(request, "You don't have permission for curated external imports.")
                return redirect(upload_url)

            job_id = request.POST.get("curated_import_job_id")
            job = CuratedImportJob.objects.filter(id=job_id, owner=workspace_user).first()
            if job is None:
                messages.error(request, "Curated import job was not found.")
                return redirect(upload_url)
            if not job.can_retry:
                messages.info(request, "Only failed curated import jobs can be retried.")
                return redirect(upload_url)

            job = run_curated_import_job(job)
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    external_import_result=self._curated_import_result(job),
                ),
            )

        if action in {
            self.ACTION_VALIDATE_EXTERNAL_IMPORT,
            self.ACTION_RUN_EXTERNAL_IMPORT,
            self.ACTION_RUN_CURATED_FILE_PIPELINE,
        }:
            if not request.user.has_perm("tpweb.can_curated_import"):
                messages.error(request, "You don't have permission for curated external imports.")
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
                load_ligq_output=cleaned.get("load_ligq_output")
                and action == self.ACTION_RUN_CURATED_FILE_PIPELINE,
                include_plan=action == self.ACTION_RUN_CURATED_FILE_PIPELINE,
                archive=cleaned.get("archive") or "",
                archive_root=cleaned.get("archive_root") or "",
            )
            try:
                summary = validate_external_import(
                    cleaned["genome_name"],
                    cleaned["results_tsv"],
                    structures_dir=cleaned.get("structures_dir") or "",
                    datadir=cleaned["datadir"],
                    ligq_output_dir=cleaned.get("ligq_output_dir") or "",
                    archive=cleaned.get("archive") or "",
                    archive_root=cleaned.get("archive_root") or "",
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

            if action == self.ACTION_VALIDATE_EXTERNAL_IMPORT:
                job = create_curated_import_job(workspace_user, cleaned, command, summary)
                result = self._curated_import_result(job, summary=summary, command=command)

            elif action == self.ACTION_RUN_CURATED_FILE_PIPELINE:
                job = create_curated_import_job(
                    workspace_user,
                    cleaned,
                    command,
                    summary,
                    status=CuratedImportJob.STATUS_RUNNING,
                )
                job = run_curated_import_job(job)
                result = self._curated_import_result(job, summary=summary, command=command)

            elif action == self.ACTION_RUN_EXTERNAL_IMPORT:
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
                    result.update(
                        {
                            "status": "imported",
                            "message": "Curated external import completed.",
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
            # A superuser's "Recent submissions" list also shows public-workspace
            # uploads (see _build_context above) -- clear those too, or the button
            # silently leaves them behind since they're owned by the shared
            # "public" user, not this request's own workspace_user.
            clear_owners = [workspace_user]
            if request.user.is_superuser:
                clear_owners.append(get_public_workspace_user())

            if any(owner_has_active_uploads(owner) for owner in clear_owners):
                messages.error(
                    request,
                    "Remove or finish queued/running uploads before clearing this history.",
                )
                return redirect(upload_url)

            deleted_count = sum(clear_genome_upload_history(owner) for owner in clear_owners)
            if deleted_count:
                messages.success(request, "Genome upload history was cleared.")
            else:
                messages.info(request, "There was no genome upload history to clear.")
            return redirect(upload_url)

        if action == self.ACTION_CLEAR_FAILED_HISTORY:
            # Only touches STATUS_FAILED rows, so unlike ACTION_CLEAR_HISTORY
            # there's no active-upload guard needed -- a queued/running job is
            # never in this set, so it can never be cancelled by this action.
            clear_owners = [workspace_user]
            if request.user.is_superuser:
                clear_owners.append(get_public_workspace_user())

            deleted_count = sum(
                clear_genome_upload_history(owner, statuses=[GenomeUpload.STATUS_FAILED])
                for owner in clear_owners
            )
            if deleted_count:
                messages.success(request, "Failed genome uploads were cleared.")
            else:
                messages.info(request, "There were no failed genome uploads to clear.")
            return redirect(upload_url)

        if not request.user.has_perm("tpweb.can_upload_genome"):
            messages.error(request, "You don't have permission to upload genomes.")
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
                if (
                    GenomeUpload.objects.select_for_update()
                    .filter(
                        owner=workspace_user,
                        internal_accession=internal_accession,
                        status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
                    )
                    .exists()
                ):
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
            messages.success(
                request, f"Test genome {TEST_GENOME_ACCESSION} was added to the queue."
            )
            return redirect(upload_url)

        form = GenomeUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, self._build_context(request, form=form))

        display_accession = form.cleaned_data["accession"]

        # Only a superuser's own checked box counts -- anyone else POSTing
        # make_public=on gets silently ignored, not an error, since it's a
        # convenience toggle, not something worth failing the whole upload
        # over.
        upload_as_public = bool(form.cleaned_data.get("make_public")) and request.user.is_superuser
        if upload_as_public:
            upload_owner = get_public_workspace_user()
            internal_accession = (
                f"{PUBLIC_WORKSPACE_USERNAME}{WORKSPACE_GENOME_DELIMITER}{display_accession}"
            )
        else:
            upload_owner = workspace_user
            internal_accession = build_workspace_genome_name(display_accession, request.user)

        if Biodatabase.objects.filter(name=internal_accession).exists():
            messages.info(
                request,
                f"Genome {display_accession} has already been processed.",
            )
            return redirect(upload_url)

        with transaction.atomic():
            if (
                GenomeUpload.objects.select_for_update()
                .filter(
                    owner=upload_owner,
                    internal_accession=internal_accession,
                    status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
                )
                .exists()
            ):
                messages.error(
                    request,
                    f"Genome {display_accession} is already queued or running for this account.",
                )
                return redirect(upload_url)

            GenomeUpload.objects.create(
                owner=upload_owner,
                display_accession=display_accession,
                internal_accession=internal_accession,
                gram=form.cleaned_data["gram"],
                gbk_file=form.cleaned_data["gbk_file"],
                status=GenomeUpload.STATUS_SUBMITTED,
            )
        messages.success(request, f"Genome {display_accession} was added to the queue.")
        return redirect(upload_url)

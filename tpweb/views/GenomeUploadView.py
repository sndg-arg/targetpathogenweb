from django.shortcuts import render
from django.views import View

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
)
from tpweb.services.pipeline_status import get_pipeline_status
from tpweb.services.pipeline_status import sanitize_pipeline_status_for_user
from tpweb.services.workspace import resolve_workspace_user


class GenomeUploadView(View):
    template_name = "user/upload_data.html"
    ACTION_CLEAR_HISTORY = "clear_history"
    ACTION_USE_TEST_GENOME = "use_test_genome"

    @staticmethod
    def _job_state(job, pipeline_status, queue_positions):
        if pipeline_status.get("running") and (
            str(pipeline_status.get("genome_accession") or "").strip() == job.internal_accession
        ):
            return {"label": "Running", "class": "running"}
        if job.status == GenomeUpload.STATUS_SUBMITTED:
            queue_position = queue_positions.get(job.id)
            return {
                "label": f"Queued #{queue_position}" if queue_position else "Queued",
                "class": "queued",
            }
        return {"label": job.get_status_display(), "class": job.status}

    def _build_context(self, request, form=None, success_message="", error_message=""):
        workspace_user = resolve_workspace_user(request.user)
        pipeline_status = sanitize_pipeline_status_for_user(get_pipeline_status(), request.user)
        reconcile_genome_uploads(pipeline_status, owner=workspace_user)
        queue_positions = build_queue_position_map()
        jobs = list(
            GenomeUpload.objects.filter(owner=workspace_user).order_by("-created_at", "-id")[:8]
        )

        jobs_dto = []
        for job in jobs:
            state = self._job_state(job, pipeline_status, queue_positions)
            jobs_dto.append(
                {
                    "id": job.id,
                    "display_accession": job.display_accession,
                    "internal_accession": job.internal_accession,
                    "gram": "Gram-negative" if job.gram == "n" else "Gram-positive",
                    "created_at": job.created_at,
                    "created_at_label": format_upload_timestamp(job.created_at),
                    "state_label": state["label"],
                    "state_class": state["class"],
                    "queue_position": queue_positions.get(job.id),
                    "protein_workspace_url": job.internal_accession,
                }
            )

        running_genome = pipeline_status.get("genome_display_accession") or pipeline_status.get(
            "genome_accession"
        )
        return {
            "form": form or GenomeUploadForm(),
            "jobs": jobs_dto,
            "test_genome_accession": TEST_GENOME_ACCESSION,
            "workspace_label": (
                workspace_user.username if request.user.is_authenticated else "public"
            ),
            "pipeline_status": pipeline_status,
            "has_active_jobs": owner_has_active_uploads(workspace_user),
            "success_message": success_message,
            "error_message": error_message,
            "running_genome_label": display_genome_name(running_genome),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._build_context(request))

    def post(self, request, *args, **kwargs):
        workspace_user = resolve_workspace_user(request.user)

        if request.POST.get("action") == self.ACTION_CLEAR_HISTORY:
            if owner_has_active_uploads(workspace_user):
                return render(
                    request,
                    self.template_name,
                    self._build_context(
                        request,
                        error_message=(
                            "Remove or finish queued/running uploads before clearing this history."
                        ),
                    ),
                )

            deleted_count = clear_genome_upload_history(workspace_user)
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    success_message=(
                        "Genome upload history was cleared."
                        if deleted_count
                        else "There was no genome upload history to clear."
                    ),
                ),
            )

        if request.POST.get("action") == self.ACTION_USE_TEST_GENOME:
            internal_accession = build_workspace_genome_name(TEST_GENOME_ACCESSION, request.user)
            if GenomeUpload.objects.filter(
                owner=workspace_user,
                internal_accession=internal_accession,
                status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
            ).exists():
                return render(
                    request,
                    self.template_name,
                    self._build_context(
                        request,
                        form=GenomeUploadForm(),
                        error_message=(
                            f"Genome {TEST_GENOME_ACCESSION} is already queued or running for this workspace."
                        ),
                    ),
                )

            GenomeUpload.objects.create(
                owner=workspace_user,
                display_accession=TEST_GENOME_ACCESSION,
                internal_accession=internal_accession,
                gram="n",
                gbk_file="",
                status=GenomeUpload.STATUS_SUBMITTED,
            )

            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    form=GenomeUploadForm(),
                    success_message=f"Test genome {TEST_GENOME_ACCESSION} was added to the queue.",
                ),
            )

        form = GenomeUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, self._build_context(request, form=form))

        display_accession = form.cleaned_data["accession"]
        internal_accession = build_workspace_genome_name(display_accession, request.user)
        if GenomeUpload.objects.filter(
            owner=workspace_user,
            internal_accession=internal_accession,
            status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING],
        ).exists():
            return render(
                request,
                self.template_name,
                self._build_context(
                    request,
                    form=form,
                    error_message=(
                        f"Genome {display_accession} is already queued or running for this workspace."
                    ),
                ),
            )

        GenomeUpload.objects.create(
            owner=workspace_user,
            display_accession=display_accession,
            internal_accession=internal_accession,
            gram=form.cleaned_data["gram"],
            gbk_file=form.cleaned_data["gbk_file"],
            status=GenomeUpload.STATUS_SUBMITTED,
        )

        return render(
            request,
            self.template_name,
            self._build_context(
                request,
                form=GenomeUploadForm(),
                success_message=f"Genome {display_accession} was added to the queue.",
            ),
        )

from pathlib import Path

from django.db.models import Q
from django.utils import timezone

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models import GenomeUpload, PipelineRun
from tpweb.services.pipeline_runs import latest_pipeline_run_for_accession, latest_pipeline_run_for_upload


ARGENTINA_UPLOAD_TZ = timezone.get_fixed_timezone(-180)

# A RUNNING job with no PipelineRun and no progress for this many seconds is
# considered orphaned (orchestrator crashed before registering, queue worker
# died, etc.) and reconciled to FAILED. Generous to avoid racing legitimate
# startups on a busy cluster.
STALE_RUNNING_GRACE_SECONDS = 600


def format_upload_timestamp(value):
    if value is None:
        return ""
    localized = timezone.localtime(value, ARGENTINA_UPLOAD_TZ)
    return localized.strftime("%Y-%m-%d %H:%M")


def _dataset_ready(internal_accession):
    if not internal_accession:
        return False
    return Biodatabase.objects.filter(name=internal_accession).exists()


def _read_log_tail(log_path, max_lines=80):
    path = Path(str(log_path or "").strip())
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    return lines[-max_lines:]


def _extract_error_message(job):
    for line in reversed(_read_log_tail(job.run_log_path)):
        text = str(line or "").strip()
        lower = text.lower()
        if not text:
            continue
        if "traceback" in lower:
            continue
        if "error" in lower or "exception" in lower or "dependencyerror" in lower:
            return text[:1000]
    return "Pipeline stopped before completion."


def _latest_run_for_upload(job):
    run = latest_pipeline_run_for_upload(job.id)
    if run is not None:
        return run

    run = latest_pipeline_run_for_accession(job.internal_accession)
    if run is None:
        return None

    # Legacy/manual runs may not be linked to a GenomeUpload. Those runs are
    # useful only while still active. A cancelled/failed historical run with
    # the same accession must not poison newer uploads created from the UI.
    if run.genome_upload_id is None and run.status not in {
        run.STATUS_SUBMITTED,
        run.STATUS_RUNNING,
    }:
        return None

    return run


def reconcile_genome_uploads(pipeline_status=None, owner=None):
    """Bring GenomeUpload rows in sync with PipelineRun.

    PipelineRun is the single source of truth. We never grep host processes
    or read PIDs — those are unreliable across container boundaries and
    racy during orchestrator startup. The only fallbacks are:
      - dataset_ready (Biodatabase exists)  → FINISHED
      - RUNNING with no PipelineRun for > grace period  → FAILED (orphan)

    The ``pipeline_status`` argument is accepted for backwards compatibility
    with existing callers but is intentionally ignored.
    """
    del pipeline_status  # unused — kept for backwards compatibility

    queryset = GenomeUpload.objects.all()
    if owner is not None:
        queryset = queryset.filter(owner=owner)

    active_pipeline_statuses = [PipelineRun.STATUS_SUBMITTED, PipelineRun.STATUS_RUNNING]
    active_run_upload_ids = list(
        PipelineRun.objects.filter(
            status__in=active_pipeline_statuses,
            genome_upload_id__isnull=False,
        ).values_list("genome_upload_id", flat=True)
    )
    active_legacy_accessions = list(
        PipelineRun.objects.filter(
            status__in=active_pipeline_statuses,
            genome_upload_id__isnull=True,
        ).values_list("internal_accession", flat=True)
    )

    queryset = queryset.filter(
        Q(status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING])
        | Q(status=GenomeUpload.STATUS_FAILED, id__in=active_run_upload_ids)
        | Q(status=GenomeUpload.STATUS_FAILED, internal_accession__in=active_legacy_accessions)
    )

    # When multiple jobs share the same internal_accession, only the one with
    # the highest ID is the active run. Older ones must not be promoted to
    # RUNNING just because the accession is processing.
    from django.db.models import Max
    latest_id_by_accession = dict(
        GenomeUpload.objects.values("internal_accession")
        .annotate(max_id=Max("id"))
        .values_list("internal_accession", "max_id")
    )

    now = timezone.now()

    for job in queryset:
        is_latest_for_accession = job.id == latest_id_by_accession.get(job.internal_accession)
        next_status = job.status
        next_error = job.error_message

        pipeline_run = _latest_run_for_upload(job)
        if pipeline_run is not None and pipeline_run.genome_upload_id not in {None, job.id}:
            pipeline_run = None
        if pipeline_run is not None and pipeline_run.genome_upload_id is None and not is_latest_for_accession:
            pipeline_run = None

        if pipeline_run is not None:
            if pipeline_run.status == pipeline_run.STATUS_RUNNING:
                next_status = GenomeUpload.STATUS_RUNNING
                next_error = ""
            elif pipeline_run.status == pipeline_run.STATUS_SUBMITTED:
                next_status = (
                    GenomeUpload.STATUS_RUNNING
                    if is_latest_for_accession
                    else GenomeUpload.STATUS_SUBMITTED
                )
                next_error = ""
            elif pipeline_run.status == pipeline_run.STATUS_FINISHED:
                if _dataset_ready(job.internal_accession):
                    next_status = GenomeUpload.STATUS_FINISHED
                    next_error = ""
                else:
                    next_status = GenomeUpload.STATUS_FAILED
                    next_error = _extract_error_message(job)
            elif pipeline_run.status in {pipeline_run.STATUS_FAILED, pipeline_run.STATUS_CANCELLED}:
                next_status = GenomeUpload.STATUS_FAILED
                next_error = str(pipeline_run.error_message or _extract_error_message(job))[:1000]
        else:
            # No PipelineRun (yet). Trust the current state. Only escalate
            # to FINISHED/FAILED with positive evidence.
            if _dataset_ready(job.internal_accession):
                next_status = GenomeUpload.STATUS_FINISHED
                next_error = ""
            elif job.status == GenomeUpload.STATUS_RUNNING:
                last_touch = job.updated_at or job.created_at
                age = (now - last_touch).total_seconds() if last_touch else 0
                if age > STALE_RUNNING_GRACE_SECONDS:
                    next_status = GenomeUpload.STATUS_FAILED
                    next_error = (
                        _extract_error_message(job)
                        or "Pipeline orchestrator never registered a run."
                    )
            # SUBMITTED jobs with no PipelineRun stay SUBMITTED — the queue
            # worker may legitimately take a long time to pick them up.

        updates = []
        if job.status != next_status:
            job.status = next_status
            updates.append("status")
        if job.error_message != next_error:
            job.error_message = next_error
            updates.append("error_message")
        if (
            next_status not in {GenomeUpload.STATUS_RUNNING, GenomeUpload.STATUS_SUBMITTED}
            and job.launch_pid is not None
        ):
            job.launch_pid = None
            updates.append("launch_pid")
        if updates:
            updates.append("updated_at")
            job.save(update_fields=updates)

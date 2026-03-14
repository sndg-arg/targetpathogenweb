import os
from pathlib import Path

from django.utils import timezone

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models import GenomeUpload


ARGENTINA_UPLOAD_TZ = timezone.get_fixed_timezone(-180)


def format_upload_timestamp(value):
    if value is None:
        return ""
    localized = timezone.localtime(value, ARGENTINA_UPLOAD_TZ)
    return localized.strftime("%Y-%m-%d %H:%M")


def _process_exists(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


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


def reconcile_genome_uploads(pipeline_status, owner=None):
    queryset = GenomeUpload.objects.all()
    if owner is not None:
        queryset = queryset.filter(owner=owner)
    queryset = queryset.filter(
        status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING]
    )

    running_internal = str(pipeline_status.get("genome_accession") or "").strip()
    pipeline_running = bool(pipeline_status.get("running"))
    pipeline_state_label = str(pipeline_status.get("state_label") or "").strip().lower()

    for job in queryset:
        next_status = job.status
        next_error = job.error_message
        pipeline_failed_for_job = (
            not pipeline_running
            and running_internal == job.internal_accession
            and pipeline_state_label in {
                "last pipeline run failed",
                "last pipeline run stopped before completion",
            }
        )

        if job.status == GenomeUpload.STATUS_SUBMITTED:
            next_status = GenomeUpload.STATUS_SUBMITTED
            next_error = ""
        elif pipeline_running and running_internal == job.internal_accession:
            next_status = GenomeUpload.STATUS_RUNNING
            next_error = ""
        elif pipeline_failed_for_job:
            next_status = GenomeUpload.STATUS_FAILED
            next_error = _extract_error_message(job)
        elif _process_exists(job.launch_pid):
            next_status = GenomeUpload.STATUS_RUNNING
            next_error = ""
        elif _dataset_ready(job.internal_accession):
            next_status = GenomeUpload.STATUS_FINISHED
            next_error = ""
        else:
            next_status = GenomeUpload.STATUS_FAILED
            next_error = _extract_error_message(job)

        updates = []
        if job.status != next_status:
            job.status = next_status
            updates.append("status")
        if job.error_message != next_error:
            job.error_message = next_error
            updates.append("error_message")
        if next_status != GenomeUpload.STATUS_RUNNING and job.launch_pid is not None:
            job.launch_pid = None
            updates.append("launch_pid")
        if updates:
            updates.append("updated_at")
            job.save(update_fields=updates)

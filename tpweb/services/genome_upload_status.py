import os
import shlex
import subprocess
from pathlib import Path

from django.db import models
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


def _pipeline_process_lines():
    try:
        ps_output = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
    except Exception:
        return []
    return ps_output.splitlines()


def _tokenize_process_command(command):
    text = str(command or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except Exception:
        return text.split()


def _upload_has_matching_process(job):
    expected_accession = str(getattr(job, "internal_accession", "") or "").strip()
    if not expected_accession:
        return False

    expected_pid = None
    try:
        expected_pid = int(job.launch_pid) if job.launch_pid is not None else None
    except (TypeError, ValueError):
        expected_pid = None

    for line in _pipeline_process_lines():
        text = str(line or "").strip()
        if not text:
            continue

        parts = text.split(None, 1)
        if len(parts) != 2:
            continue

        pid_text, command = parts
        try:
            pid = int(pid_text)
        except (TypeError, ValueError):
            pid = None

        tokens = _tokenize_process_command(command)
        if "run_pipeline.py" not in {Path(token).name for token in tokens}:
            continue

        if expected_pid is not None and pid == expected_pid:
            return True

        if "--genome-name" not in tokens:
            continue

        try:
            accession = tokens[tokens.index("--genome-name") + 1].strip()
        except Exception:
            accession = ""
        if accession == expected_accession:
            return True

    return False


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

    # When multiple jobs share the same internal_accession, only the one with
    # the highest ID is the active run. All older ones must be resolved to failed/finished.
    from django.db.models import Max
    latest_id_by_accession = dict(
        GenomeUpload.objects.values("internal_accession")
        .annotate(max_id=Max("id"))
        .values_list("internal_accession", "max_id")
    )

    for job in queryset:
        is_latest_for_accession = job.id == latest_id_by_accession.get(job.internal_accession)
        next_status = job.status
        next_error = job.error_message
        matching_process_exists = _process_exists(job.launch_pid) or _upload_has_matching_process(job)
        pipeline_failed_for_job = (
            not pipeline_running
            and running_internal == job.internal_accession
            and pipeline_state_label in {
                "last pipeline run failed",
                "last pipeline run stopped before completion",
            }
        )

        if job.status == GenomeUpload.STATUS_SUBMITTED:
            if matching_process_exists or (pipeline_running and running_internal == job.internal_accession and is_latest_for_accession):
                next_status = GenomeUpload.STATUS_RUNNING
                next_error = ""
            else:
                next_status = GenomeUpload.STATUS_SUBMITTED
                next_error = ""
        elif pipeline_running and running_internal == job.internal_accession and is_latest_for_accession:
            next_status = GenomeUpload.STATUS_RUNNING
            next_error = ""
        elif matching_process_exists and is_latest_for_accession:
            next_status = GenomeUpload.STATUS_RUNNING
            next_error = ""
        elif pipeline_failed_for_job:
            next_status = GenomeUpload.STATUS_FAILED
            next_error = _extract_error_message(job)
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

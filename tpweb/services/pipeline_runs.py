import os
import signal
import subprocess

from django.db.models import Case, IntegerField, Value, When
from django.db import transaction
from django.utils import timezone

from tpweb.services.pipeline_stages import STAGE_LABELS


def _ensure_django():
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def _models():
    _ensure_django()
    from tpweb.models.PipelineRun import PipelineRun, PipelineStageEvent

    return PipelineRun, PipelineStageEvent


def create_pipeline_run(
    *,
    genome_upload_id=None,
    internal_accession,
    source_accession="",
    gram="",
    custom_input="",
    run_log_path="",
    metadata=None,
):
    PipelineRun, _ = _models()
    metadata = dict(metadata or {})
    upload = None
    if genome_upload_id:
        from tpweb.models import GenomeUpload

        upload = GenomeUpload.objects.filter(pk=genome_upload_id).first()

    run = PipelineRun.objects.create(
        genome_upload=upload,
        internal_accession=internal_accession,
        source_accession=source_accession,
        gram=gram,
        custom_input=custom_input,
        run_log_path=run_log_path,
        metadata=metadata,
        status=PipelineRun.STATUS_SUBMITTED,
    )
    return run


def mark_pipeline_run_started(run_id, *, pid=None, run_log_path=""):
    PipelineRun, _ = _models()
    updates = {
        "status": PipelineRun.STATUS_RUNNING,
        "updated_at": timezone.now(),
    }
    if pid is not None:
        updates["launch_pid"] = pid
    if run_log_path:
        updates["run_log_path"] = run_log_path
    PipelineRun.objects.filter(pk=run_id).update(**updates)


def record_pipeline_stage_event(
    run_id,
    *,
    stage_number=None,
    app_name="",
    task_id=None,
    status="info",
    message="",
    payload=None,
):
    PipelineRun, PipelineStageEvent = _models()
    payload = dict(payload or {})
    stage_label = STAGE_LABELS.get(stage_number, "") if stage_number else ""

    with transaction.atomic():
        run = PipelineRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None:
            return

        PipelineStageEvent.objects.create(
            pipeline_run=run,
            stage_number=stage_number,
            stage_label=stage_label,
            app_name=app_name,
            task_id=task_id,
            status=status,
            message=message,
            payload=payload,
        )

        updates = []
        if stage_number is not None and status in {
            PipelineStageEvent.STATUS_SUBMITTED,
            PipelineStageEvent.STATUS_RUNNING,
            PipelineStageEvent.STATUS_COMPLETED,
            PipelineStageEvent.STATUS_FAILED,
            PipelineStageEvent.STATUS_INFO,
        }:
            current_stage = run.current_stage or 0
            if stage_number >= current_stage or status == PipelineStageEvent.STATUS_FAILED:
                run.current_stage = stage_number
                run.current_stage_label = stage_label
                updates.extend(["current_stage", "current_stage_label"])
        if app_name and status != PipelineStageEvent.STATUS_SUBMITTED:
            run.current_app = app_name
            updates.append("current_app")
        if task_id is not None and status != PipelineStageEvent.STATUS_SUBMITTED:
            run.current_task_id = task_id
            updates.append("current_task_id")
        if status == PipelineStageEvent.STATUS_FAILED and message:
            run.error_message = str(message)[:1000]
            updates.append("error_message")
        if updates:
            run.updated_at = timezone.now()
            updates.append("updated_at")
            run.save(update_fields=list(dict.fromkeys(updates)))


def record_interproscan_remote_job(run_id, *, job_id, remote_job_dir=""):
    PipelineRun, _ = _models()
    updates = {
        "remote_job_id": str(job_id or "").strip(),
        "updated_at": timezone.now(),
    }
    if remote_job_dir:
        updates["remote_job_dir"] = str(remote_job_dir).strip()
    PipelineRun.objects.filter(pk=run_id).update(**updates)
    record_pipeline_stage_event(
        run_id,
        stage_number=10,
        app_name="interproscan",
        status="info",
        message=f"Submitted remote InterProScan job {job_id}",
        payload={"remote_job_id": str(job_id or "").strip(), "remote_job_dir": remote_job_dir},
    )


def finalize_pipeline_run(run_id, *, status, error_message=""):
    PipelineRun, _ = _models()
    run = PipelineRun.objects.filter(pk=run_id).first()
    if run is None:
        return

    final_status = status
    if final_status not in {
        PipelineRun.STATUS_FINISHED,
        PipelineRun.STATUS_FAILED,
        PipelineRun.STATUS_CANCELLED,
    }:
        final_status = PipelineRun.STATUS_FAILED

    updates = {
        "status": final_status,
        "finished_at": timezone.now(),
        "updated_at": timezone.now(),
    }
    if error_message or final_status != PipelineRun.STATUS_FINISHED:
        updates["error_message"] = str(error_message or run.error_message or "")[:1000]
    if final_status != PipelineRun.STATUS_RUNNING:
        updates["launch_pid"] = None
    if final_status == PipelineRun.STATUS_FINISHED:
        updates["current_stage"] = max(run.current_stage or 0, max(STAGE_LABELS))
        updates["current_stage_label"] = STAGE_LABELS[max(STAGE_LABELS)]
        updates["error_message"] = ""
    PipelineRun.objects.filter(pk=run_id).update(**updates)


def latest_pipeline_run():
    PipelineRun, _ = _models()
    return PipelineRun.objects.order_by("-started_at", "-id").first()


def latest_active_pipeline_run():
    PipelineRun, _ = _models()
    return (
        PipelineRun.objects.filter(
            status__in=[PipelineRun.STATUS_SUBMITTED, PipelineRun.STATUS_RUNNING]
        )
        .annotate(
            status_rank=Case(
                When(status=PipelineRun.STATUS_RUNNING, then=Value(0)),
                When(status=PipelineRun.STATUS_SUBMITTED, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("status_rank", "-started_at", "-id")
        .first()
    )


def latest_pipeline_run_for_accession(internal_accession):
    PipelineRun, _ = _models()
    return (
        PipelineRun.objects.filter(internal_accession=internal_accession)
        .order_by("-started_at", "-id")
        .first()
    )


def latest_pipeline_run_for_upload(upload_id):
    PipelineRun, _ = _models()
    return (
        PipelineRun.objects.filter(genome_upload_id=upload_id)
        .order_by("-started_at", "-id")
        .first()
    )


def _scancel_remote_job(job_id):
    ssh_host = str(os.getenv("SSH_HOSTNAME") or "").strip()
    ssh_user = str(os.getenv("SSH_USERNAME") or "").strip()
    if not ssh_host or not ssh_user or not job_id:
        return False

    target = f"{ssh_user}@{ssh_host}"
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, f"scancel {job_id}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def cancel_pipeline_run(run):
    PipelineRun, _ = _models()
    if run is None:
        return False

    cancelled = False
    pid = getattr(run, "launch_pid", None)
    if pid:
        try:
            os.killpg(int(pid), signal.SIGTERM)
            cancelled = True
        except Exception:
            try:
                os.kill(int(pid), signal.SIGTERM)
                cancelled = True
            except Exception:
                pass

    remote_job_id = str(getattr(run, "remote_job_id", "") or "").strip()
    remote_cancelled = False
    if remote_job_id:
        remote_cancelled = _scancel_remote_job(remote_job_id)
        cancelled = cancelled or remote_cancelled

    run.status = PipelineRun.STATUS_CANCELLED
    run.error_message = "Pipeline run cancelled."
    run.finished_at = timezone.now()
    run.launch_pid = None
    run.updated_at = timezone.now()
    run.save(
        update_fields=["status", "error_message", "finished_at", "launch_pid", "updated_at"]
    )

    record_pipeline_stage_event(
        run.id,
        stage_number=run.current_stage,
        app_name=run.current_app,
        task_id=run.current_task_id,
        status="failed",
        message=(
            "Pipeline run cancelled"
            + (f"; remote job {remote_job_id} cancelled" if remote_cancelled else "")
        ),
        payload={"remote_job_id": remote_job_id},
    )
    return cancelled

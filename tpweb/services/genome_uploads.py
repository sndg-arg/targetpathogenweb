import os
import shlex
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models import GenomeUpload
from tpweb.services.pipeline_status import clear_pipeline_activity_state
from tpweb.services.pipeline_runs import cancel_pipeline_run, latest_pipeline_run_for_accession, latest_pipeline_run_for_upload


TEST_GENOME_ACCESSION = "NZ_AP023069.1"


def _build_pipeline_runtime(upload, command_suffix):
    parsl_dir = Path(settings.BASE_DIR) / "parsl"
    log_dir = Path(settings.MEDIA_ROOT) / "pipeline_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"genome-upload-{upload.id}.log"

    env = os.environ.copy()
    base_dir = str(settings.BASE_DIR)
    existing_pythonpath = env.get("PYTHONPATH", "")
    python_bin_dir = str(Path(sys.executable).resolve().parent)
    existing_path = env.get("PATH", "")
    pythonpath_parts = [base_dir, str(parsl_dir)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = ":".join(pythonpath_parts)
    env["PATH"] = f"{python_bin_dir}:{existing_path}" if existing_path else python_bin_dir
    env.setdefault("DJANGO_SETTINGS_MODULE", "tpwebconfig.settings")
    env["TPW_GENOME_UPLOAD_ID"] = str(upload.id)
    env["TPW_PIPELINE_LOG_PATH"] = str(log_path)

    command = [
        "bash",
        "-lc",
        (
            f"source {shlex.quote(str(parsl_dir / 'exports.sh'))} && "
            f"{shlex.quote(sys.executable)} run_pipeline.py "
            f"{command_suffix}"
        ),
    ]

    return {
        "command": command,
        "cwd": str(parsl_dir),
        "env": env,
        "log_path": log_path,
    }


def _mark_upload_running(upload, process_pid, log_path):
    upload.launch_pid = process_pid
    upload.run_log_path = str(log_path)
    upload.status = upload.STATUS_RUNNING
    upload.launched_at = timezone.now()
    upload.error_message = ""
    upload.save(update_fields=["launch_pid", "run_log_path", "status", "launched_at", "error_message", "updated_at"])
    return process_pid


def _dataset_ready(internal_accession):
    return Biodatabase.objects.filter(name=internal_accession).exists()


def _workspace_biodatabase_names(internal_accession):
    accession = str(internal_accession or "").strip()
    if not accession:
        return []

    suffixes = (
        "",
        getattr(Biodatabase, "PROT_POSTFIX", "_prots"),
        getattr(Biodatabase, "RNA_POSTFIX", "_rnas"),
    )
    names = []
    for suffix in suffixes:
        candidate = f"{accession}{suffix}" if suffix else accession
        if candidate not in names:
            names.append(candidate)
    return names


def _delete_workspace_biodatabases(internal_accession):
    biodatabase_names = _workspace_biodatabase_names(internal_accession)
    if not biodatabase_names:
        return
    Biodatabase.objects.filter(name__in=biodatabase_names).delete()


def _delete_upload_artifacts(upload):
    if upload.gbk_file:
        upload.gbk_file.delete(save=False)

    run_log_path = str(upload.run_log_path or "").strip()
    if run_log_path:
        try:
            Path(run_log_path).unlink(missing_ok=True)
        except Exception:
            pass


def _read_log_tail(log_path, max_lines=80):
    path = Path(str(log_path or "").strip())
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    return lines[-max_lines:]


def _extract_error_message(log_path):
    for line in reversed(_read_log_tail(log_path)):
        text = str(line or "").strip()
        lower = text.lower()
        if not text:
            continue
        if "traceback" in lower:
            continue
        if "error" in lower or "exception" in lower or "dependencyerror" in lower:
            return text[:1000]
    return "Pipeline stopped before completion."


def _upload_was_deleted(upload):
    upload_id = getattr(upload, "pk", None)
    if not upload_id:
        return True
    return not GenomeUpload.objects.filter(pk=upload_id).exists()


def _finalize_upload(upload, returncode):
    if _upload_was_deleted(upload):
        _delete_upload_artifacts(upload)
        _delete_workspace_biodatabases(upload.internal_accession)
        if not GenomeUpload.objects.exists():
            clear_pipeline_activity_state()
        return upload.STATUS_FAILED

    if returncode == 0 and _dataset_ready(upload.internal_accession):
        upload.status = upload.STATUS_FINISHED
        upload.error_message = ""
    else:
        upload.status = upload.STATUS_FAILED
        upload.error_message = _extract_error_message(upload.run_log_path)
    upload.launch_pid = None
    upload.save(update_fields=["status", "error_message", "launch_pid", "updated_at"])
    return upload.status


def _build_command_suffix(upload):
    base = f"--gram {upload.gram} --genome-name {shlex.quote(upload.internal_accession)} "
    if upload.gbk_file:
        return f"{base}--custom {shlex.quote(upload.gbk_file.path)}"
    return f"{base}--test"


def launch_genome_upload_pipeline(upload):
    runtime = _build_pipeline_runtime(upload, _build_command_suffix(upload))
    log_handle = open(runtime["log_path"], "ab")
    try:
        process = subprocess.Popen(
            runtime["command"],
            cwd=runtime["cwd"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=runtime["env"],
            start_new_session=True,
        )
    finally:
        log_handle.close()

    return _mark_upload_running(upload, process.pid, runtime["log_path"])


def launch_test_genome_pipeline(upload):
    return launch_genome_upload_pipeline(upload)


def run_genome_upload_pipeline(upload):
    runtime = _build_pipeline_runtime(upload, _build_command_suffix(upload))
    log_handle = open(runtime["log_path"], "ab")
    try:
        process = subprocess.Popen(
            runtime["command"],
            cwd=runtime["cwd"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=runtime["env"],
            start_new_session=True,
        )
        _mark_upload_running(upload, process.pid, runtime["log_path"])
        returncode = process.wait()
    finally:
        log_handle.close()

    return _finalize_upload(upload, returncode)


def dequeue_next_genome_upload():
    with transaction.atomic():
        return (
            GenomeUpload.objects.select_for_update(skip_locked=True)
            .filter(status=GenomeUpload.STATUS_SUBMITTED)
            .order_by("created_at", "id")
            .first()
        )


def build_queue_position_map():
    queued_ids = list(
        GenomeUpload.objects.filter(status=GenomeUpload.STATUS_SUBMITTED)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    return {upload_id: index + 1 for index, upload_id in enumerate(queued_ids)}


def owner_has_active_uploads(owner):
    return owner.genome_uploads.filter(
        status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING]
    ).exists()


def workspace_has_active_upload(internal_accession, owner=None):
    uploads = GenomeUpload.objects.filter(internal_accession=internal_accession)
    if owner is not None:
        uploads = uploads.filter(owner=owner)
    return uploads.filter(
        status__in=[GenomeUpload.STATUS_SUBMITTED, GenomeUpload.STATUS_RUNNING]
    ).exists()


def delete_genome_workspace(internal_accession, owner=None):
    uploads = GenomeUpload.objects.filter(internal_accession=internal_accession)
    if owner is not None:
        uploads = uploads.filter(owner=owner)

    deleted_uploads = 0
    for upload in list(uploads):
        active_run = latest_pipeline_run_for_upload(upload.id) or latest_pipeline_run_for_accession(
            upload.internal_accession
        )
        if active_run and active_run.status in {
            active_run.STATUS_SUBMITTED,
            active_run.STATUS_RUNNING,
        }:
            cancel_pipeline_run(active_run)
        _delete_upload_artifacts(upload)
        upload.delete()
        deleted_uploads += 1

    _delete_workspace_biodatabases(internal_accession)

    if not GenomeUpload.objects.exists():
        clear_pipeline_activity_state()

    return deleted_uploads


def clear_genome_upload_history(owner):
    uploads = list(owner.genome_uploads.all())
    deleted_count = 0

    for upload in uploads:
        active_run = latest_pipeline_run_for_upload(upload.id) or latest_pipeline_run_for_accession(
            upload.internal_accession
        )
        if active_run and active_run.status in {
            active_run.STATUS_SUBMITTED,
            active_run.STATUS_RUNNING,
        }:
            cancel_pipeline_run(active_run)
        if upload.status != GenomeUpload.STATUS_FINISHED:
            _delete_workspace_biodatabases(upload.internal_accession)

        _delete_upload_artifacts(upload)
        upload.delete()
        deleted_count += 1

    if not GenomeUpload.objects.exists():
        clear_pipeline_activity_state()

    return deleted_count

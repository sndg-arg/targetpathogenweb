import logging
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tpweb.models import CuratedImportJob
from tpweb.services.curated_pipeline import compute_folder_path

logger = logging.getLogger(__name__)


def create_curated_import_job(owner, cleaned_data, command, summary, *, status=None):
    return CuratedImportJob.objects.create(
        owner=owner,
        genome_name=cleaned_data["genome_name"],
        results_tsv=cleaned_data["results_tsv"],
        structures_dir=cleaned_data.get("structures_dir") or "",
        archive=cleaned_data.get("archive") or "",
        archive_root=cleaned_data.get("archive_root") or "",
        ligq_output_dir=cleaned_data.get("ligq_output_dir") or "",
        datadir=cleaned_data["datadir"],
        overwrite_scores=cleaned_data["overwrite"],
        load_ligq_output=bool(cleaned_data.get("load_ligq_output")),
        status=status or CuratedImportJob.STATUS_VALIDATED,
        phase=status or CuratedImportJob.STATUS_VALIDATED,
        command=command,
        summary_json=summary,
    )


def running_curated_import(user):
    """The curated import running now, for the home status card (staff only)."""
    if not getattr(user, "is_authenticated", False) or not user.has_perm(
        "tpweb.can_curated_import"
    ):
        return None
    return (
        CuratedImportJob.objects.filter(status=CuratedImportJob.STATUS_RUNNING)
        .order_by("-started_at", "-id")
        .first()
    )


def _log_path_for_job(job):
    folder = Path(compute_folder_path(job.datadir, job.genome_name)) / "curated_import"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"curated-import-{job.pk}.log"


def _job_command(job):
    command = [
        sys.executable,
        str(Path(settings.BASE_DIR) / "manage.py"),
        "run_curated_file_import",
        "--genome",
        job.genome_name,
        "--results-tsv",
        job.results_tsv,
        "--datadir",
        job.datadir,
        "--execute",
        "--job-id",
        str(job.pk),
    ]
    for flag, value in (
        ("--structures-dir", job.structures_dir),
        ("--archive", job.archive),
        ("--archive-root", job.archive_root),
        ("--ligq-output-dir", job.ligq_output_dir),
    ):
        if value:
            command += [flag, value]
    if job.archive:
        command += ["--extract", "--overwrite-extract"]
    if job.overwrite_scores:
        command.append("--overwrite-scores")
    if not job.load_ligq_output:
        command.append("--skip-ligq")
    return command


def _launch(job_pk):
    job = CuratedImportJob.objects.get(pk=job_pk)
    try:
        log_path = _log_path_for_job(job)
        with open(log_path, "ab") as log:
            subprocess.Popen(
                _job_command(job),
                cwd=str(settings.BASE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        logger.exception("Could not start curated import job %s", job.pk)
        job.status = CuratedImportJob.STATUS_FAILED
        job.phase = "failed"
        job.error_message = f"Could not start the import: {exc}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "phase", "error_message", "finished_at", "updated_at"])
        return
    job.stdout = f"Log: {log_path}"
    job.save(update_fields=["stdout", "updated_at"])


def run_curated_import_job(job):
    """Start the import in its own process and return at once: a full genome
    takes hours, far longer than a web request may run. The command marks
    the job running/finished/failed itself (--job-id)."""
    job.status = CuratedImportJob.STATUS_RUNNING
    job.phase = "starting"
    job.started_at = timezone.now()
    job.finished_at = None
    job.stdout = ""
    job.stderr = ""
    job.report_text = ""
    job.error_message = ""
    job.save(
        update_fields=[
            "status",
            "phase",
            "started_at",
            "finished_at",
            "stdout",
            "stderr",
            "report_text",
            "error_message",
            "updated_at",
        ]
    )
    # The request transaction must commit first, or the new process can't see the job.
    transaction.on_commit(lambda: _launch(job.pk))
    return job

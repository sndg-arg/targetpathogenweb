from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from tpweb.models import CuratedImportJob


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


def _report_path_for_job(job):
    report_dir = Path(settings.MEDIA_ROOT) / "curated_import_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir / f"curated-import-{job.pk}.txt"


def run_curated_import_job(job):
    stdout = StringIO()
    stderr = StringIO()
    report_path = _report_path_for_job(job)

    job.status = CuratedImportJob.STATUS_RUNNING
    job.phase = "running"
    job.started_at = timezone.now()
    job.finished_at = None
    job.stdout = ""
    job.stderr = ""
    job.report_path = str(report_path)
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
            "report_path",
            "report_text",
            "error_message",
            "updated_at",
        ]
    )

    try:
        call_command(
            "run_curated_file_import",
            genome=job.genome_name,
            results_tsv=job.results_tsv,
            structures_dir=job.structures_dir or None,
            archive=job.archive or None,
            archive_root=job.archive_root or None,
            ligq_output_dir=job.ligq_output_dir or None,
            datadir=job.datadir,
            execute=True,
            extract=bool(job.archive),
            overwrite_extract=bool(job.archive),
            overwrite_scores=job.overwrite_scores,
            skip_ligq=not job.load_ligq_output,
            report=str(report_path),
            stdout=stdout,
            stderr=stderr,
        )
    except Exception as exc:
        job.status = CuratedImportJob.STATUS_FAILED
        job.phase = "failed"
        job.error_message = str(exc)
    else:
        job.status = CuratedImportJob.STATUS_FINISHED
        job.phase = "finished"

    job.stdout = stdout.getvalue()
    job.stderr = stderr.getvalue()
    if report_path.exists():
        job.report_text = report_path.read_text(encoding="utf-8", errors="replace")
    job.finished_at = timezone.now()
    job.save(
        update_fields=[
            "status",
            "phase",
            "error_message",
            "stdout",
            "stderr",
            "report_text",
            "finished_at",
            "updated_at",
        ]
    )
    return job

import json
import logging
import shutil
import threading
import time
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from bioseq.models.Biodatabase import Biodatabase
from django.conf import settings
from django.db.utils import DatabaseError
from tpweb.services.genome_workspace import display_genome_name, user_can_access_genome_name
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME, workspace_slug_for_user
from tpweb.services.pipeline_runs import latest_active_pipeline_run, latest_pipeline_run
from tpweb.services.pipeline_stages import PIPELINE_STAGE_TOTAL, STAGE_LABELS
from tpweb.services.slurm_messages import classify_slurm_resource_message

logger = logging.getLogger(__name__)

ARGENTINA_TZ = timezone(timedelta(hours=-3))
PIPELINE_STATUS_CACHE_TTL_SECONDS = float(
    os.getenv("TPW_PIPELINE_STATUS_CACHE_TTL_SECONDS", "4")
)
_PIPELINE_STATUS_CACHE: dict = {
    "expires_at": 0.0,
    "status": None,
}
_PIPELINE_STATUS_CACHE_LOCK = threading.Lock()
LAST_RUN_MARKER_RELATIVE_PATHS = (
    "data/pipeline/last_pipeline_run.json",
    "pipeline/last_pipeline_run.json",
    "last_pipeline_run.json",
)
# Legacy Parsl runinfo dirs — kept here only so clear_pipeline_activity_state()
# can wipe leftover files on disk during a reset.
LEGACY_RUNINFO_RELATIVE_DIRS = ("data/pipeline/runinfo", "pipeline/runinfo", "runinfo")
FAILED_PIPELINE_STATE_LABELS = {"Last pipeline run failed"}
INCOMPLETE_PIPELINE_STATE_LABELS = FAILED_PIPELINE_STATE_LABELS | {
    "Last pipeline run stopped before completion"
}
PIPELINE_EVENT_TERMINAL_STATUSES = {"completed", "failed"}


@dataclass(frozen=True)
class PipelineStatus:
    available: bool = False
    running: bool = False
    state_label: str = "No pipeline activity detected"
    state_class: str = "idle"
    stage_current: int | None = None
    stage_total: int = PIPELINE_STAGE_TOTAL
    stage_label: str | None = None
    progress_percent: int = 0
    task_id: int | None = None
    run_id: str | None = None
    last_updated: str | None = None
    genome_accession: str | None = None
    genome_display_accession: str | None = None
    activity_label: str | None = None
    workspace_slug: str | None = None
    workspace_owner_id: int | None = None
    stages_completed: tuple = ()
    stages_active: tuple = ()

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LastRunMarker:
    status: str
    finished_at: datetime
    genome_accession: str | None
    marker_path: Path


def _parse_utc_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _load_last_run_marker(base_dir: Path):
    marker_path = None
    for relative in LAST_RUN_MARKER_RELATIVE_PATHS:
        candidate = base_dir / relative
        if candidate.exists() and candidate.is_file():
            marker_path = candidate
            break

    if marker_path is None:
        return None

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    status_raw = str(marker.get("status") or "").strip().lower()
    if status_raw not in {"finished", "failed"}:
        return None

    finished_at = _parse_utc_iso(marker.get("finished_at_utc"))
    if finished_at is None:
        finished_at = datetime.fromtimestamp(marker_path.stat().st_mtime, tz=timezone.utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)

    genomes = marker.get("genomes")
    genome_accession = None
    if isinstance(genomes, list) and genomes:
        genome_accession = str(genomes[0]).strip().upper() or None

    return LastRunMarker(
        status=status_raw,
        finished_at=finished_at,
        genome_accession=genome_accession,
        marker_path=marker_path,
    )


def _status_from_last_run_marker(base_dir: Path):
    marker = _load_last_run_marker(base_dir)
    if marker is None:
        return None
    updated_at_ar = marker.finished_at.astimezone(ARGENTINA_TZ).strftime("%Y-%m-%d %H:%M (UTC-3)")

    status_data = _default_pipeline_status().as_dict()
    status_data["available"] = True
    status_data["running"] = False
    status_data["run_id"] = f"marker:{marker.marker_path.name}"
    status_data["last_updated"] = updated_at_ar
    status_data["genome_accession"] = marker.genome_accession
    status_data["genome_display_accession"] = display_genome_name(marker.genome_accession)

    if marker.status == "finished":
        status_data["state_label"] = "Last pipeline run finished"
        status_data["state_class"] = "finished"
        status_data["stage_current"] = PIPELINE_STAGE_TOTAL
        status_data["stage_label"] = STAGE_LABELS.get(PIPELINE_STAGE_TOTAL)
        status_data["progress_percent"] = 100
    else:
        status_data["state_label"] = "Last pipeline run failed"
        status_data["state_class"] = "failed"

    return PipelineStatus(**status_data)


def _activity_label_for_stage(stage_number, active_app):
    if stage_number == 4 or active_app == "fasttarget":
        return "FastTarget: computing scores"
    if stage_number == 10 or active_app == "interproscan":
        return "InterProScan: domain annotation"
    if stage_number == 14 or active_app == "alphafold_unips":
        return "AlphaFold: model generation"
    return None


def _default_pipeline_status() -> PipelineStatus:
    return PipelineStatus()


def _current_running_upload():
    try:
        from tpweb.models import GenomeUpload
    except Exception:
        return None

    return (
        GenomeUpload.objects.filter(status=GenomeUpload.STATUS_RUNNING)
        .order_by("-launched_at", "-updated_at", "-id")
        .first()
    )


def _status_from_running_upload(upload):
    if upload is None:
        return None

    status_data = _default_pipeline_status().as_dict()
    status_data["available"] = True
    status_data["running"] = True
    status_data["state_label"] = "Pipeline running"
    status_data["state_class"] = "running"
    status_data["run_id"] = f"upload:{upload.id}"
    status_data["genome_accession"] = str(upload.internal_accession or "").strip() or None
    status_data["genome_display_accession"] = display_genome_name(
        status_data["genome_accession"]
    )
    status_data["activity_label"] = "Genome upload in progress"

    timestamp = None
    run_log_path = Path(str(getattr(upload, "run_log_path", "") or "").strip())
    if run_log_path.exists() and run_log_path.is_file():
        try:
            timestamp = datetime.fromtimestamp(run_log_path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            timestamp = None

    if timestamp is None:
        timestamp = getattr(upload, "updated_at", None) or getattr(upload, "launched_at", None)
        if timestamp is not None and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

    if timestamp is not None:
        status_data["last_updated"] = timestamp.astimezone(ARGENTINA_TZ).strftime(
            "%Y-%m-%d %H:%M (UTC-3)"
        )

    return PipelineStatus(**status_data)


def _format_pipeline_timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ARGENTINA_TZ).strftime("%Y-%m-%d %H:%M (UTC-3)")


def _progress_percent(stage_number):
    if stage_number is None or stage_number <= 0:
        return 0
    return int((stage_number / PIPELINE_STAGE_TOTAL) * 100)


def _active_stage_from_pipeline_run(run):
    stage_events = list(run.stage_events.order_by("created_at", "id"))
    latest_by_task = {}
    latest_stage_event = None
    latest_failed_event = None
    latest_info_event = None
    for event in stage_events:
        if event.stage_number is not None:
            latest_stage_event = event
        if event.status == "failed" and event.stage_number is not None:
            latest_failed_event = event
        if event.status == "info" and event.stage_number is not None:
            latest_info_event = event
        if event.task_id is not None:
            latest_by_task[event.task_id] = event

    # Collect completed and active stage numbers from all tracked tasks
    completed_stages = set()
    active_stages = set()
    for event in latest_by_task.values():
        if event.stage_number is None:
            continue
        if event.status == "completed":
            completed_stages.add(event.stage_number)
        elif event.status not in PIPELINE_EVENT_TERMINAL_STATUSES:
            active_stages.add(event.stage_number)

    pending_events = [
        event
        for event in latest_by_task.values()
        if event.status not in PIPELINE_EVENT_TERMINAL_STATUSES
    ]
    pending_events.sort(
        key=lambda event: (
            event.stage_number if event.stage_number is not None else PIPELINE_STAGE_TOTAL + 1,
            event.task_id if event.task_id is not None else -1,
        )
    )

    # For stage_current, use the highest active stage (best progress indicator)
    active_event = pending_events[-1] if pending_events else None
    display_event = active_event

    if display_event is not None:
        return {
            "stage_number": display_event.stage_number,
            "task_id": display_event.task_id,
            "app_name": display_event.app_name,
            "failed_event": latest_failed_event,
            "info_event": latest_info_event,
            "latest_stage_event": latest_stage_event,
            "stages_completed": tuple(sorted(completed_stages)),
            "stages_active": tuple(sorted(active_stages)),
        }

    if latest_failed_event is not None:
        return {
            "stage_number": latest_failed_event.stage_number,
            "task_id": latest_failed_event.task_id,
            "app_name": latest_failed_event.app_name,
            "failed_event": latest_failed_event,
            "info_event": latest_info_event,
            "latest_stage_event": latest_stage_event,
            "stages_completed": tuple(sorted(completed_stages)),
            "stages_active": tuple(sorted(active_stages)),
        }

    return {
        "stage_number": run.current_stage or (latest_stage_event.stage_number if latest_stage_event else None),
        "task_id": run.current_task_id,
        "app_name": run.current_app or (latest_stage_event.app_name if latest_stage_event else ""),
        "failed_event": latest_failed_event,
        "info_event": latest_info_event,
        "latest_stage_event": latest_stage_event,
        "stages_completed": tuple(sorted(completed_stages)),
        "stages_active": tuple(sorted(active_stages)),
    }


def _status_from_pipeline_run(run):
    if run is None:
        return None

    status_data = _default_pipeline_status().as_dict()
    status_data["available"] = True
    status_data["run_id"] = f"pipeline:{run.id}"
    genome_accession = str(run.internal_accession or "").strip() or None
    status_data["genome_accession"] = genome_accession
    status_data["genome_display_accession"] = display_genome_name(genome_accession)
    workspace_slug = None
    workspace_owner_id = None
    genome_upload = getattr(run, "genome_upload", None)
    if genome_upload is not None:
        workspace_owner_id = getattr(genome_upload, "owner_id", None)
        if workspace_owner_id:
            workspace_slug = f"user-{workspace_owner_id}"
    if workspace_slug is None and genome_accession:
        prefix = genome_accession.split("__", 1)[0].strip().lower()
        workspace_slug = prefix or None
    status_data["workspace_slug"] = workspace_slug
    status_data["workspace_owner_id"] = workspace_owner_id
    status_data["last_updated"] = _format_pipeline_timestamp(
        run.updated_at or run.finished_at or run.started_at
    )

    active_info = _active_stage_from_pipeline_run(run)
    stage_number = active_info["stage_number"]
    active_app = active_info["app_name"] or run.current_app
    task_id = active_info["task_id"]
    info_event = active_info.get("info_event")
    stages_completed = active_info.get("stages_completed", ())
    stages_active = active_info.get("stages_active", ())
    status_data["stages_completed"] = stages_completed
    status_data["stages_active"] = stages_active
    if stage_number is not None:
        status_data["stage_current"] = stage_number
        status_data["stage_label"] = STAGE_LABELS.get(stage_number)
        # Progress based on completed stages, not linear stage number
        if stages_completed:
            status_data["progress_percent"] = int(len(stages_completed) / PIPELINE_STAGE_TOTAL * 100)
        else:
            status_data["progress_percent"] = _progress_percent(stage_number)
    if task_id is not None:
        status_data["task_id"] = task_id

    if run.status == run.STATUS_FINISHED:
        status_data["running"] = False
        status_data["state_label"] = "Last pipeline run finished"
        status_data["state_class"] = "finished"
        status_data["stage_current"] = PIPELINE_STAGE_TOTAL
        status_data["stage_label"] = STAGE_LABELS.get(PIPELINE_STAGE_TOTAL)
        status_data["progress_percent"] = 100
        status_data["stages_completed"] = tuple(range(1, PIPELINE_STAGE_TOTAL + 1))
        status_data["stages_active"] = ()
        return PipelineStatus(**status_data)

    if run.status == run.STATUS_FAILED:
        status_data["running"] = False
        status_data["state_label"] = "Last pipeline run failed"
        status_data["state_class"] = "failed"
        return PipelineStatus(**status_data)

    if run.status == run.STATUS_CANCELLED:
        status_data["running"] = False
        status_data["state_label"] = "Last pipeline run cancelled"
        status_data["state_class"] = "failed"
        return PipelineStatus(**status_data)

    status_data["running"] = True
    if run.status == run.STATUS_SUBMITTED:
        status_data["state_label"] = "Pipeline queued"
    else:
        status_data["state_label"] = "Pipeline running"
    status_data["state_class"] = "running"

    if stage_number is not None:
        status_data["activity_label"] = _activity_label_for_stage(
            stage_number,
            active_app,
        )
        info_message = str(getattr(info_event, "message", "") or "").strip()
        friendly_info = classify_slurm_resource_message(info_message, running=True)
        if friendly_info:
            status_data["activity_label"] = friendly_info
    elif run.status == run.STATUS_SUBMITTED:
        status_data["activity_label"] = "Genome upload queued"

    return PipelineStatus(**status_data)


def _cache_put(status: PipelineStatus, now: float) -> None:
    _PIPELINE_STATUS_CACHE["status"] = status
    _PIPELINE_STATUS_CACHE["expires_at"] = now + PIPELINE_STATUS_CACHE_TTL_SECONDS


def get_pipeline_status_dto() -> PipelineStatus:
    """Resolve current pipeline status.

    Sources of truth, in order:
      1. PipelineRun (database) — the orchestrator records every stage event.
      2. A running GenomeUpload — covers the brief window between job pickup
         and the first PipelineRun row.
      3. last_pipeline_run.json marker — surfaces the result of the most
         recent run when no DB row is available (e.g. legacy local runs).
    """
    now = time.monotonic()
    with _PIPELINE_STATUS_CACHE_LOCK:
        cached_status = _PIPELINE_STATUS_CACHE.get("status")
        expires_at = _PIPELINE_STATUS_CACHE.get("expires_at", 0.0)
        if cached_status is not None and now < expires_at:
            return cached_status

    pipeline_run = latest_active_pipeline_run() or latest_pipeline_run()
    if pipeline_run is not None:
        final_status = _status_from_pipeline_run(pipeline_run)
        with _PIPELINE_STATUS_CACHE_LOCK:
            _cache_put(final_status, now)
        return final_status

    running_upload_status = _status_from_running_upload(_current_running_upload())
    if running_upload_status is not None:
        with _PIPELINE_STATUS_CACHE_LOCK:
            _cache_put(running_upload_status, now)
        return running_upload_status

    marker_status = _status_from_last_run_marker(Path(settings.BASE_DIR))
    final_status = marker_status or _default_pipeline_status()
    with _PIPELINE_STATUS_CACHE_LOCK:
        _cache_put(final_status, now)
    return final_status


def get_pipeline_status() -> dict:
    try:
        return get_pipeline_status_dto().as_dict()
    except DatabaseError:
        logger.warning(
            "Falling back to idle pipeline status after database error.",
            exc_info=True,
        )
        return _default_pipeline_status().as_dict()


def _reset_pipeline_status_to_idle(status: dict) -> dict:
    status["genome_accession"] = None
    status["genome_display_accession"] = None
    status["run_id"] = None
    status["last_updated"] = None
    status["task_id"] = None
    status["activity_label"] = None
    status["stage_current"] = None
    status["stage_label"] = None
    status["progress_percent"] = 0
    status["available"] = False
    status["running"] = False
    status["state_label"] = "No pipeline activity detected"
    status["state_class"] = "idle"
    return status


def sanitize_pipeline_status_for_user(pipeline_status: Mapping | None, user) -> dict:
    status = dict(pipeline_status or {})
    genome_accession = str(status.get("genome_accession") or "").strip()
    workspace_slug = str(status.get("workspace_slug") or "").strip().lower()
    workspace_owner_id = status.get("workspace_owner_id")
    current_workspace_slug = workspace_slug_for_user(user)
    public_workspace_prefix = f"{PUBLIC_WORKSPACE_USERNAME}__"
    public_workspace_run = workspace_slug == PUBLIC_WORKSPACE_USERNAME or (
        current_workspace_slug == PUBLIC_WORKSPACE_USERNAME
        and genome_accession.lower().startswith(public_workspace_prefix)
    )

    if public_workspace_run:
        genome_visible_to_user = True
    elif workspace_owner_id is not None and getattr(user, "is_authenticated", False):
        genome_visible_to_user = int(workspace_owner_id) == int(getattr(user, "pk", 0) or 0)
    elif workspace_slug:
        genome_visible_to_user = workspace_slug in {
            PUBLIC_WORKSPACE_USERNAME,
            current_workspace_slug,
        }
    else:
        genome_visible_to_user = not genome_accession or user_can_access_genome_name(user, genome_accession)
    genome_hidden_from_user = bool(genome_accession) and not genome_visible_to_user
    genome_exists = True
    if genome_accession and not status.get("running"):
        genome_exists = Biodatabase.objects.filter(name=genome_accession).exists()
    stale_deleted_genome = bool(genome_accession) and not status.get("running") and not genome_exists

    status["genome_visible_to_user"] = genome_visible_to_user
    status["genome_exists"] = genome_exists
    status["workspace_slug"] = workspace_slug or None
    status["workspace_owner_id"] = workspace_owner_id
    status["running_for_other_workspace"] = bool(
        status.get("running") and genome_hidden_from_user
    )

    if stale_deleted_genome:
        return _reset_pipeline_status_to_idle(status)

    if genome_hidden_from_user:
        status["genome_accession"] = None
        status["genome_display_accession"] = None
        status["run_id"] = None
        status["last_updated"] = None
        status["task_id"] = None
        status["activity_label"] = None
        status["stage_current"] = None
        status["stage_label"] = None
        status["progress_percent"] = 0

        if status["running_for_other_workspace"]:
            status["available"] = True
            status["running"] = True
            status["state_label"] = "Pipeline busy"
            status["state_class"] = "running"
        else:
            _reset_pipeline_status_to_idle(status)

    return status


def clear_pipeline_activity_state():
    active_run = None
    try:
        from tpweb.services.pipeline_runs import latest_active_pipeline_run

        active_run = latest_active_pipeline_run()
    except Exception:
        active_run = None

    with _PIPELINE_STATUS_CACHE_LOCK:
        _PIPELINE_STATUS_CACHE["status"] = None
        _PIPELINE_STATUS_CACHE["expires_at"] = 0.0

    # Keep runtime state intact while a pipeline run is still active. Removing
    # runinfo mid-flight leaves HTEX workers alive but blind, which looks like a
    # hung pipeline from the UI.
    if active_run is not None:
        return

    base_dir = Path(settings.BASE_DIR)
    for relative in LAST_RUN_MARKER_RELATIVE_PATHS:
        try:
            (base_dir / relative).unlink(missing_ok=True)
        except Exception:
            pass

    for relative in LEGACY_RUNINFO_RELATIVE_DIRS:
        runinfo_dir = base_dir / relative
        if not runinfo_dir.exists() or not runinfo_dir.is_dir():
            continue
        for child in runinfo_dir.iterdir():
            if not child.is_dir():
                continue
            try:
                shutil.rmtree(child)
            except Exception:
                pass

def annotate_pipeline_status_for_genome(
    pipeline_status: Mapping | None, genome_accession: str | None
) -> dict:
    status = dict(pipeline_status or {})
    target_genome = (genome_accession or "").strip().upper()
    running_genome = (status.get("genome_accession") or "").strip().upper()
    running = bool(status.get("running"))
    state_label = str(status.get("state_label") or "").strip()
    matches_current_genome = bool(target_genome and running_genome == target_genome)

    status["running_for_current_genome"] = bool(
        running and matches_current_genome
    )
    status["running_for_other_genome"] = bool(
        running and running_genome and target_genome and running_genome != target_genome
    )
    status["other_genome_accession"] = (
        status.get("genome_accession") if status["running_for_other_genome"] else None
    )
    status["other_genome_display_accession"] = (
        display_genome_name(status.get("other_genome_accession"))
        if status.get("other_genome_accession")
        else None
    )
    status["failed_for_current_genome"] = bool(
        not running and matches_current_genome and state_label in FAILED_PIPELINE_STATE_LABELS
    )
    status["incomplete_for_current_genome"] = bool(
        not running and matches_current_genome and state_label in INCOMPLETE_PIPELINE_STATE_LABELS
    )
    if status["failed_for_current_genome"]:
        status["current_genome_status_note"] = (
            "This genome workspace is incomplete because the last pipeline run failed."
        )
    elif status["incomplete_for_current_genome"]:
        status["current_genome_status_note"] = (
            "This genome workspace is incomplete because the last pipeline run stopped before completion."
        )
    else:
        status["current_genome_status_note"] = None
    return status


def annotate_pipeline_status_for_genomes(
    genomes: list[Mapping] | tuple[Mapping, ...], pipeline_status: Mapping | None
) -> list[dict]:
    annotated_genomes = []
    for genome in genomes:
        genome_data = dict(genome)
        genome_data.update(
            annotate_pipeline_status_for_genome(
                pipeline_status, genome_data.get("internal_name")
            )
        )
        annotated_genomes.append(genome_data)
    return annotated_genomes

import json
import re
import shlex
import shutil
import subprocess
import time
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from bioseq.models.Biodatabase import Biodatabase
from django.conf import settings
from tpweb.services.genome_workspace import display_genome_name, user_can_access_genome_name

# Main pipeline stages from parsl/run_pipeline.py.
PIPELINE_STAGE_TOTAL = 23
INPUT_APPS = {"test_gbk", "download_gbk", "custom_gbk"}
STAGE_LABELS = {
    1: "Cleaning previous output",
    2: "Loading genome input",
    3: "Importing genome records",
    4: "Running FastTarget scoring",
    5: "Loading human offtarget score",
    6: "Loading microbiome offtarget score",
    7: "Loading essentiality score",
    8: "Building DB indexes",
    9: "Indexing sequence files",
    10: "Running InterProScan",
    11: "Loading InterPro annotations",
    12: "Mapping to UniProt",
    13: "Fetching UniProt annotations",
    14: "Collecting UniProt list",
    15: "Generating AlphaFold models",
    16: "Predicting missing structures (ESMFold)",
    17: "Loading structures and pockets",
    18: "Computing druggability table",
    19: "Loading druggability score",
    20: "Predicting subcellular localization",
    21: "Loading PSORT score",
    22: "Collecting binder candidates",
    23: "Loading binders",
}
ARGENTINA_TZ = timezone(timedelta(hours=-3))
PIPELINE_STATUS_CACHE_TTL_SECONDS = float(
    os.getenv("TPW_PIPELINE_STATUS_CACHE_TTL_SECONDS", "4")
)
_PIPELINE_STATUS_CACHE: dict = {
    "expires_at": 0.0,
    "status": None,
}
RUNINFO_CANDIDATE_RELATIVE_DIRS = ("data/parsl/runinfo", "parsl/runinfo", "runinfo")
LAST_RUN_MARKER_RELATIVE_PATHS = (
    "data/parsl/last_pipeline_run.json",
    "parsl/last_pipeline_run.json",
    "last_pipeline_run.json",
)
FAILED_PIPELINE_STATE_LABELS = {"Last pipeline run failed"}
INCOMPLETE_PIPELINE_STATE_LABELS = FAILED_PIPELINE_STATE_LABELS | {
    "Last pipeline run stopped before completion"
}


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

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LastRunMarker:
    status: str
    finished_at: datetime
    genome_accession: str | None
    marker_path: Path


def _latest_run_dir(runinfo_dir: Path):
    run_dirs = [p for p in runinfo_dir.iterdir() if p.is_dir()]
    if not run_dirs:
        return None

    def _run_dir_mtime(path: Path):
        log_path = path / "parsl.log"
        try:
            if log_path.exists():
                return log_path.stat().st_mtime
            return path.stat().st_mtime
        except Exception:
            return 0.0

    return max(run_dirs, key=_run_dir_mtime)


def _candidate_runinfo_dirs(base_dir: Path):
    for relative in RUNINFO_CANDIDATE_RELATIVE_DIRS:
        candidate = base_dir / relative
        if candidate.exists() and candidate.is_dir():
            yield candidate


def _resolve_runinfo_dir(base_dir: Path):
    candidates = list(_candidate_runinfo_dirs(base_dir))
    if not candidates:
        return None

    # Prefer the directory that has a newer run.
    latest_by_dir = []
    for candidate in candidates:
        latest_run = _latest_run_dir(candidate)
        if latest_run is None:
            latest_by_dir.append((candidate, 0.0))
            continue
        log_path = latest_run / "parsl.log"
        try:
            mtime = log_path.stat().st_mtime if log_path.exists() else latest_run.stat().st_mtime
        except Exception:
            mtime = 0.0
        latest_by_dir.append((candidate, mtime))
    latest_by_dir.sort(key=lambda item: item[1], reverse=True)
    return latest_by_dir[0][0]


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


def _ps_args_lines():
    try:
        ps_output = subprocess.check_output(["ps", "-eo", "args"], text=True)
    except Exception:
        return []
    return ps_output.splitlines()


def _tokenize_process_args(line):
    text = str(line or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except Exception:
        return text.split()


def _process_invokes_script(tokens, script_name):
    if not tokens:
        return False
    return any(Path(token).name == script_name for token in tokens)


def _pipeline_process_running(ps_lines=None):
    ps_lines = ps_lines if ps_lines is not None else _ps_args_lines()
    for line in ps_lines:
        tokens = _tokenize_process_args(line)
        if (
            _process_invokes_script(tokens, "run_pipeline.py")
            or _process_invokes_script(tokens, "fasttarget.py")
            or _process_invokes_script(tokens, "process_worker_pool.py")
        ):
            return True
    return False


def _extract_running_genome_from_process(ps_lines=None):
    ps_lines = ps_lines if ps_lines is not None else _ps_args_lines()
    for line in ps_lines:
        tokens = _tokenize_process_args(line)
        if not _process_invokes_script(tokens, "run_pipeline.py"):
            continue

        if "--genome-name" in tokens:
            try:
                return tokens[tokens.index("--genome-name") + 1].strip() or None
            except Exception:
                return None

        if "--test" in tokens or "-t" in tokens:
            return "NZ_AP023069.1"

        if "--custom" in tokens:
            try:
                custom_path = tokens[tokens.index("--custom") + 1]
            except Exception:
                custom_path = None
            if custom_path:
                return Path(custom_path).name.split(".g")[0]
        if "-c" in tokens:
            try:
                custom_path = tokens[tokens.index("-c") + 1]
            except Exception:
                custom_path = None
            if custom_path:
                return Path(custom_path).name.split(".g")[0]

        positional = []
        skip_next = False
        options_with_values = {"--gram", "--custom", "--genome-name", "-c"}
        for token in tokens:
            if skip_next:
                skip_next = False
                continue
            if token in options_with_values:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            if token in {">", "1>", "2>", ">>", "2>>"}:
                break
            positional.append(token)
        if positional:
            return positional[0].strip().upper()

    return None


def _fasttarget_activity_label(ps_lines=None):
    ps_lines = ps_lines if ps_lines is not None else _ps_args_lines()
    for line in ps_lines:
        lower = line.lower()
        if "blastp" not in lower:
            continue
        if "/app/fasttarget/" not in lower:
            continue
        if "microbiome_offtarget" in lower:
            return "FastTarget: microbiome BLAST"
        if "human_offtarget" in lower:
            return "FastTarget: human BLAST"
        if "essentiality" in lower:
            return "FastTarget: essentiality BLAST"
        return "FastTarget: BLAST search"

    if any("fasttarget.py" in line for line in ps_lines):
        return "FastTarget: computing scores"
    return None


def _activity_label_for_stage(stage_number, active_app, ps_lines=None):
    if stage_number == 4 or active_app == "fasttarget":
        return _fasttarget_activity_label(ps_lines=ps_lines) or "FastTarget: computing scores"
    if stage_number == 10 or active_app == "interproscan":
        return "InterProScan: domain annotation"
    if stage_number == 14 or active_app == "alphafold_unips":
        return "AlphaFold: model generation"
    return None


def _extract_genome_from_run_logs(run_dir: Path):
    candidates = []
    task_logs_dir = run_dir / "task_logs"
    if task_logs_dir.exists():
        candidates.extend(sorted(task_logs_dir.glob("**/*.stderr")))
        candidates.extend(sorted(task_logs_dir.glob("**/*.stdout")))

    explicit_accession_patterns = [
        re.compile(r"accession:\s*([A-Za-z0-9._-]+(?:__[A-Za-z0-9._-]+)?)"),
        re.compile(r"--accession\s+([A-Za-z0-9._-]+(?:__[A-Za-z0-9._-]+)?)"),
        re.compile(r"--genome-name\s+([A-Za-z0-9._-]+(?:__[A-Za-z0-9._-]+)?)"),
    ]
    fallback_accession_re = re.compile(r"\b([A-Za-z0-9._-]+__[A-Za-z0-9._-]+|[A-Z]{1,6}_[A-Z0-9]+(?:\.[0-9]+)?)\b")

    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pattern in explicit_accession_patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()

        match = fallback_accession_re.search(text)
        if match:
            return match.group(1).strip()
    return None


def _stage_from_app(app_name, load_score_seen):
    if app_name == "clear_folder":
        return 1
    if app_name in INPUT_APPS:
        return 2
    if app_name == "load_gbk":
        return 3
    if app_name == "fasttarget":
        return 4
    if app_name == "load_score":
        mapping = {1: 5, 2: 6, 3: 7, 4: 19, 5: 21}
        return mapping.get(load_score_seen, 21)
    if app_name == "index_genome_db":
        return 8
    if app_name == "index_genome_seq":
        return 9
    if app_name == "interproscan":
        return 10
    if app_name == "load_interpro":
        return 11
    if app_name == "gbk2uniprot_map":
        return 12
    if app_name == "fetch_uniprot_annotations":
        return 13
    if app_name == "get_unipslst":
        return 14
    if app_name == "alphafold_unips":
        return 15
    if app_name == "esmfold_predict":
        return 16
    if app_name == "strucutures_af":
        return 17
    if app_name in {"fpocket2json", "load_pocket", "p2rank2json", "load_p2pocket", "load_af_model"}:
        return 17
    if app_name == "druggability_2_csv":
        return 18
    if app_name == "psort":
        return 20
    if app_name == "get_binders":
        return 22
    if app_name == "load_binders":
        return 23
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


def _stage_by_task_id(tracked_tasks: Mapping[int, str]) -> dict[int, int | None]:
    # The pipeline has multiple load_score calls at different stages.
    # Sub-tasks spawned by join_apps (strucutures_af) can have higher task IDs
    # than later main-pipeline tasks, so we must track load_score order only
    # for the *first* occurrence of each load_score task_id in submission order.
    #
    # Pipeline order of load_score: human_offtarget(5), micro_offtarget(6),
    # essentiality(7), druggability(19), psort(21).
    #
    # Strategy: find the first task_id for each non-repeatable app to anchor
    # the main pipeline spine, then assign load_score ordinals only to task_ids
    # that appear in this spine.
    sorted_ids = sorted(tracked_tasks.keys())

    # Build the "main spine": for apps that appear exactly once in the pipeline
    # (everything except alphafold_unips, load_af_model, fpocket2json, etc.),
    # take the first task_id.  For load_score, keep all task_ids that appear
    # *before* any sub-task app (load_af_model, fpocket2json, load_pocket,
    # p2rank2json, load_p2pocket) OR *after* strucutures_af completes.
    SUB_TASK_APPS = {"load_af_model", "fpocket2json", "load_pocket", "p2rank2json", "load_p2pocket"}

    # Identify which load_score tasks belong to the main pipeline.
    # They are the ones whose task_id is NOT between the first sub-task and
    # the last sub-task.
    sub_task_ids = [tid for tid in sorted_ids if tracked_tasks[tid] in SUB_TASK_APPS]
    sub_range = (min(sub_task_ids), max(sub_task_ids)) if sub_task_ids else (None, None)

    load_score_order = {}
    load_score_count = 0
    for task_id in sorted_ids:
        if tracked_tasks[task_id] != "load_score":
            continue
        # Skip load_score tasks that fall within the sub-task range
        if sub_range[0] is not None and sub_range[0] <= task_id <= sub_range[1]:
            continue
        load_score_count += 1
        load_score_order[task_id] = load_score_count

    stage_by_task = {}
    for task_id in sorted_ids:
        app_name = tracked_tasks[task_id]
        ls_seen = load_score_order.get(task_id, load_score_count)
        stage_by_task[task_id] = _stage_from_app(app_name, ls_seen)
    return stage_by_task


def get_pipeline_status_dto() -> PipelineStatus:
    now = time.monotonic()
    cached_status = _PIPELINE_STATUS_CACHE.get("status")
    expires_at = _PIPELINE_STATUS_CACHE.get("expires_at", 0.0)
    if cached_status is not None and now < expires_at:
        return cached_status

    status = _default_pipeline_status()
    running_upload = _current_running_upload()
    running_upload_status = _status_from_running_upload(running_upload)

    base_dir = Path(settings.BASE_DIR)
    last_run_marker = _load_last_run_marker(base_dir)
    runinfo_dir = _resolve_runinfo_dir(base_dir)
    if runinfo_dir is None:
        marker_status = _status_from_last_run_marker(base_dir)
        return running_upload_status or marker_status or status

    latest_run = _latest_run_dir(runinfo_dir)
    if latest_run is None:
        marker_status = _status_from_last_run_marker(base_dir)
        return running_upload_status or marker_status or status

    log_path = latest_run / "parsl.log"
    if not log_path.exists():
        marker_status = _status_from_last_run_marker(base_dir)
        return running_upload_status or marker_status or status

    updated_at_ar = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc).astimezone(
        ARGENTINA_TZ
    )
    status_data = status.as_dict()
    status_data["available"] = True
    status_data["run_id"] = latest_run.name
    status_data["last_updated"] = updated_at_ar.strftime("%Y-%m-%d %H:%M (UTC-3)")

    submitted_re = re.compile(r"Task (\d+) submitted for App ([^,]+),")
    completed_re = re.compile(r"Task (\d+) completed ")

    submitted = {}
    completed = set()
    cleanup_complete = False

    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            submitted_match = submitted_re.search(line)
            if submitted_match:
                task_id = int(submitted_match.group(1))
                app_name = submitted_match.group(2).strip()
                submitted[task_id] = app_name
                continue

            completed_match = completed_re.search(line)
            if completed_match:
                completed.add(int(completed_match.group(1)))
                continue

            if "DFK cleanup complete" in line:
                cleanup_complete = True

    tracked = {task_id: app for task_id, app in submitted.items() if app != "run"}
    if not tracked:
        return running_upload_status or PipelineStatus(**status_data)

    stage_by_task = _stage_by_task_id(tracked)
    pending_task_ids = sorted([task_id for task_id in tracked if task_id not in completed])
    ps_lines = _ps_args_lines()
    running_upload_accession = None
    if running_upload is not None:
        running_upload_accession = str(running_upload.internal_accession or "").strip() or None
    log_genome_accession = _extract_genome_from_run_logs(latest_run)
    running_by_upload = bool(running_upload_accession) and (
        not log_genome_accession or log_genome_accession == running_upload_accession
    )
    process_running = _pipeline_process_running(ps_lines=ps_lines)
    # Fallback: if the pipeline runs in a separate container (different PID namespace),
    # ps won't see it. Use log recency as an alternative signal — if parsl.log was
    # written within the last 30 s, something is actively running.
    log_recently_updated = (time.time() - log_path.stat().st_mtime) < 30
    if running_upload_status is not None and not process_running and not log_recently_updated:
        final_status = running_upload_status
        _PIPELINE_STATUS_CACHE["status"] = final_status
        _PIPELINE_STATUS_CACHE["expires_at"] = now + PIPELINE_STATUS_CACHE_TTL_SECONDS
        return final_status
    running = bool(pending_task_ids) and not cleanup_complete and (
        process_running or log_recently_updated
    )
    status_data["running"] = running

    if running:
        active_task_id = pending_task_ids[0]
        status_data["task_id"] = active_task_id
        status_data["state_label"] = "Pipeline running"
        status_data["state_class"] = "running"
    elif pending_task_ids:
        active_task_id = pending_task_ids[0]
        status_data["task_id"] = active_task_id
        status_data["state_label"] = "Last pipeline run stopped before completion"
        status_data["state_class"] = "finished"
    else:
        completed_task_ids = [task_id for task_id in tracked if task_id in completed]
        if completed_task_ids:
            active_task_id = max(
                completed_task_ids,
                key=lambda task_id: (stage_by_task.get(task_id) or -1, task_id),
            )
        else:
            active_task_id = max(tracked.keys())
        status_data["task_id"] = active_task_id
        status_data["state_label"] = "Last pipeline run finished"
        status_data["state_class"] = "finished"

    active_app = tracked.get(active_task_id)
    stage_number = stage_by_task.get(active_task_id)
    if stage_number is not None:
        status_data["stage_current"] = stage_number
        status_data["stage_label"] = STAGE_LABELS.get(stage_number)
        status_data["progress_percent"] = int((stage_number / PIPELINE_STAGE_TOTAL) * 100)
        if not running and not pending_task_ids and stage_number < PIPELINE_STAGE_TOTAL:
            status_data["state_label"] = "Last pipeline run stopped before completion"

    if running:
        status_data["activity_label"] = _activity_label_for_stage(
            stage_number, active_app, ps_lines=ps_lines
        )

    genome_accession = _extract_running_genome_from_process(ps_lines=ps_lines)
    if not genome_accession:
        genome_accession = log_genome_accession
    if running and not genome_accession and running_upload_accession:
        genome_accession = running_upload_accession
    status_data["genome_accession"] = genome_accession
    status_data["genome_display_accession"] = display_genome_name(genome_accession)

    if not running and last_run_marker is not None:
        marker_timestamp = last_run_marker.finished_at.timestamp()
        log_timestamp = log_path.stat().st_mtime
        if marker_timestamp >= log_timestamp - 5:
            if last_run_marker.status == "failed":
                status_data["state_label"] = "Last pipeline run failed"
                status_data["state_class"] = "failed"
            else:
                status_data["state_label"] = "Last pipeline run finished"
                status_data["state_class"] = "finished"
                status_data["stage_current"] = PIPELINE_STAGE_TOTAL
                status_data["stage_label"] = STAGE_LABELS.get(PIPELINE_STAGE_TOTAL)
                status_data["progress_percent"] = 100
            if not status_data.get("genome_accession"):
                status_data["genome_accession"] = last_run_marker.genome_accession
                status_data["genome_display_accession"] = display_genome_name(
                    last_run_marker.genome_accession
                )

    final_status = PipelineStatus(**status_data)
    _PIPELINE_STATUS_CACHE["status"] = final_status
    _PIPELINE_STATUS_CACHE["expires_at"] = now + PIPELINE_STATUS_CACHE_TTL_SECONDS
    return final_status


def get_pipeline_status() -> dict:
    return get_pipeline_status_dto().as_dict()


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
    genome_visible_to_user = not genome_accession or user_can_access_genome_name(user, genome_accession)
    genome_hidden_from_user = bool(genome_accession) and not genome_visible_to_user
    genome_exists = True
    if genome_accession and not status.get("running"):
        genome_exists = Biodatabase.objects.filter(name=genome_accession).exists()
    stale_deleted_genome = bool(genome_accession) and not status.get("running") and not genome_exists

    status["genome_visible_to_user"] = genome_visible_to_user
    status["genome_exists"] = genome_exists
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
    base_dir = Path(settings.BASE_DIR)
    for relative in LAST_RUN_MARKER_RELATIVE_PATHS:
        try:
            (base_dir / relative).unlink(missing_ok=True)
        except Exception:
            pass

    for relative in RUNINFO_CANDIDATE_RELATIVE_DIRS:
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

    _PIPELINE_STATUS_CACHE["status"] = None
    _PIPELINE_STATUS_CACHE["expires_at"] = 0.0


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

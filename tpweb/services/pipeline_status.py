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

from django.conf import settings
from tpweb.services.genome_workspace import display_genome_name, user_can_access_genome_name

# Main pipeline stages from parsl/run_pipeline.py.
PIPELINE_STAGE_TOTAL = 21
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
    13: "Collecting UniProt list",
    14: "Generating AlphaFold models",
    15: "Loading structures and pockets",
    16: "Computing druggability table",
    17: "Loading druggability score",
    18: "Predicting subcellular localization",
    19: "Loading PSORT score",
    20: "Collecting binder candidates",
    21: "Loading binders",
}
ARGENTINA_TZ = timezone(timedelta(hours=-3))
PIPELINE_STATUS_CACHE_TTL_SECONDS = float(
    os.getenv("TPW_PIPELINE_STATUS_CACHE_TTL_SECONDS", "4")
)
_PIPELINE_STATUS_CACHE: dict = {
    "expires_at": 0.0,
    "status": None,
}
RUNINFO_CANDIDATE_RELATIVE_DIRS = ("parsl/runinfo", "runinfo")
LAST_RUN_MARKER_RELATIVE_PATHS = ("parsl/last_pipeline_run.json", "last_pipeline_run.json")


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
        status_data["state_class"] = "finished"

    return PipelineStatus(**status_data)


def _ps_args_lines():
    try:
        ps_output = subprocess.check_output(["ps", "-eo", "args"], text=True)
    except Exception:
        return []
    return ps_output.splitlines()


def _pipeline_process_running(ps_lines=None):
    ps_lines = ps_lines if ps_lines is not None else _ps_args_lines()
    markers = ("run_pipeline.py", "fasttarget.py", "process_worker_pool.py")
    return any(marker in line for line in ps_lines for marker in markers)


def _extract_running_genome_from_process(ps_lines=None):
    ps_lines = ps_lines if ps_lines is not None else _ps_args_lines()
    for line in ps_lines:
        if "run_pipeline.py" not in line:
            continue

        marker = "run_pipeline.py"
        tail = line[line.find(marker) + len(marker):].strip()
        if not tail:
            continue

        try:
            tokens = shlex.split(tail)
        except Exception:
            tokens = tail.split()

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
        mapping = {1: 5, 2: 6, 3: 7, 4: 17, 5: 19}
        return mapping.get(load_score_seen, 19)
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
    if app_name == "get_unipslst":
        return 13
    if app_name == "alphafold_unips":
        return 14
    if app_name == "strucutures_af":
        return 15
    if app_name in {"fpocket2json", "load_pocket", "p2rank2json", "load_p2pocket"}:
        return 15
    if app_name == "druggability_2_csv":
        return 16
    if app_name == "psort":
        return 18
    if app_name == "get_binders":
        return 20
    if app_name == "load_binders":
        return 21
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


def _stage_by_task_id(tracked_tasks: Mapping[int, str]) -> dict[int, int | None]:
    load_score_seen = 0
    stage_by_task = {}
    for task_id in sorted(tracked_tasks.keys()):
        app_name = tracked_tasks[task_id]
        if app_name == "load_score":
            load_score_seen += 1
        stage_by_task[task_id] = _stage_from_app(app_name, load_score_seen)
    return stage_by_task


def get_pipeline_status_dto() -> PipelineStatus:
    now = time.monotonic()
    cached_status = _PIPELINE_STATUS_CACHE.get("status")
    expires_at = _PIPELINE_STATUS_CACHE.get("expires_at", 0.0)
    if cached_status is not None and now < expires_at:
        return cached_status

    status = _default_pipeline_status()

    base_dir = Path(settings.BASE_DIR)
    last_run_marker = _load_last_run_marker(base_dir)
    runinfo_dir = _resolve_runinfo_dir(base_dir)
    if runinfo_dir is None:
        marker_status = _status_from_last_run_marker(base_dir)
        return marker_status or status

    latest_run = _latest_run_dir(runinfo_dir)
    if latest_run is None:
        marker_status = _status_from_last_run_marker(base_dir)
        return marker_status or status

    log_path = latest_run / "parsl.log"
    if not log_path.exists():
        marker_status = _status_from_last_run_marker(base_dir)
        return marker_status or status

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
        return PipelineStatus(**status_data)

    stage_by_task = _stage_by_task_id(tracked)
    pending_task_ids = sorted([task_id for task_id in tracked if task_id not in completed])
    ps_lines = _ps_args_lines()
    running_upload = _current_running_upload()
    running_upload_accession = None
    if running_upload is not None:
        running_upload_accession = str(running_upload.internal_accession or "").strip() or None
    log_genome_accession = _extract_genome_from_run_logs(latest_run)
    running_by_upload = bool(running_upload_accession) and (
        not log_genome_accession or log_genome_accession == running_upload_accession
    )
    running = bool(pending_task_ids) and not cleanup_complete and _pipeline_process_running(
        ps_lines=ps_lines
    )
    if not running and bool(pending_task_ids) and running_by_upload:
        running = True
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
                status_data["state_class"] = "finished"
            else:
                status_data["state_label"] = "Last pipeline run finished"
                status_data["state_class"] = "finished"
                if status_data.get("stage_current") is None:
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


def sanitize_pipeline_status_for_user(pipeline_status: Mapping | None, user) -> dict:
    status = dict(pipeline_status or {})
    genome_accession = str(status.get("genome_accession") or "").strip()
    genome_visible_to_user = not genome_accession or user_can_access_genome_name(user, genome_accession)
    genome_hidden_from_user = bool(genome_accession) and not genome_visible_to_user

    status["genome_visible_to_user"] = genome_visible_to_user
    status["running_for_other_workspace"] = bool(
        status.get("running") and genome_hidden_from_user
    )

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
            status["available"] = False
            status["running"] = False
            status["state_label"] = "No pipeline activity detected"
            status["state_class"] = "idle"

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

    status["running_for_current_genome"] = bool(
        running and target_genome and running_genome == target_genome
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
    return status

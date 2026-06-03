import re
import shlex
import subprocess
import time
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from django.conf import settings

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
    activity_label: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _latest_run_dir(runinfo_dir: Path):
    run_dirs = [p for p in runinfo_dir.iterdir() if p.is_dir() and p.name.isdigit()]
    if not run_dirs:
        return None
    return sorted(run_dirs, key=lambda p: int(p.name))[-1]


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
        options_with_values = {"--gram", "--custom", "-c"}
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
    task_logs_dir = run_dir / "task_logs"
    if not task_logs_dir.exists():
        return None

    accession_re = re.compile(r"\b([A-Z]{1,6}_[A-Z0-9]+(?:\.[0-9]+)?)\b")
    stderr_files = sorted(task_logs_dir.glob("**/*.stderr"))
    for stderr_file in stderr_files:
        try:
            text = stderr_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        match = accession_re.search(text)
        if match:
            return match.group(1)
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

    runinfo_dir = Path(settings.BASE_DIR) / "parsl" / "runinfo"
    if not runinfo_dir.exists():
        return status

    latest_run = _latest_run_dir(runinfo_dir)
    if latest_run is None:
        return status

    log_path = latest_run / "parsl.log"
    if not log_path.exists():
        return status

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
    running = bool(pending_task_ids) and not cleanup_complete and _pipeline_process_running(
        ps_lines=ps_lines
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
        genome_accession = _extract_genome_from_run_logs(latest_run)
    status_data["genome_accession"] = genome_accession

    final_status = PipelineStatus(**status_data)
    _PIPELINE_STATUS_CACHE["status"] = final_status
    _PIPELINE_STATUS_CACHE["expires_at"] = now + PIPELINE_STATUS_CACHE_TTL_SECONDS
    return final_status


def get_pipeline_status() -> dict:
    return get_pipeline_status_dto().as_dict()


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
    return status

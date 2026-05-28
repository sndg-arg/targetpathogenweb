#!/usr/bin/env python
"""
Pipeline orchestrator — direct execution, no Parsl.

Replaces run_pipeline.py with plain subprocess.run() calls.
Activated via TPW_USE_DIRECT_PIPELINE=1 environment variable.
The DAG is the same 23-stage, 5-branch pipeline; branches run sequentially
(matching the current Parsl behaviour with MaxWorkers=1).
"""
import argparse
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

# Reuse helpers from the existing run_pipeline module.
from run_pipeline import (
    _pipeline_shared_dir,
    _write_last_run_marker,
    _safe_error_text,
    _pipeline_run_id,
    _record_pipeline_stage,
    _initialize_pipeline_run,
)
from pipeline_commands import (
    download_gbk_cmd,
    test_gbk_cmd,
    custom_gbk_cmd,
    load_gbk_cmd,
    sync_genome_metadata_cmd,
    fasttarget_cmd,
    load_score_cmd,
    index_db_cmd,
    index_seq_cmd,
    load_interpro_cmd,
    gbk2uniprot_cmd,
    fetch_annotations_cmd,
    fetch_exp_structures_cmd,
    alphafold_cmd,
    colabfold_cmd,
    load_af_model_cmd,
    run_fpocket_cmd,
    fpocket2json_cmd,
    load_pocket_cmd,
    run_p2rank_cmd,
    p2rank2json_cmd,
    load_p2pocket_cmd,
    druggability_cmd,
    psort_cmd,
    get_binders_cmd,
    load_binders_cmd,
)
from interproscan_remote import run_remote_interproscan
from colabfold_remote import run_remote_colabfold
from ligq_remote import run_remote_ligq
from slurm_remote_command import run_remote_shell_job
from structures_remote import run_remote_structures


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_stage(stage_number, app_name, command_str):
    """Execute a bash command, recording stage events before/after."""
    _record_pipeline_stage(stage_number, app_name, status="submitted")
    env = os.environ.copy()
    env_bin = os.path.dirname(sys.executable)
    current_path = env.get("PATH", "")
    if env_bin and env_bin not in current_path.split(os.pathsep):
        env["PATH"] = env_bin + (os.pathsep + current_path if current_path else "")
    result = subprocess.run(
        ["bash", "-c", command_str],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or "")[-1000:]
        _record_pipeline_stage(stage_number, app_name, status="failed", message=error_msg)
        raise RuntimeError(f"{app_name} failed (rc={result.returncode}): {error_msg[:500]}")
    _record_pipeline_stage(stage_number, app_name, status="completed")
    return result


def _run_python_stage(stage_number, app_name, fn, *args, **kwargs):
    """Execute a Python callable, recording stage events before/after."""
    _record_pipeline_stage(stage_number, app_name, status="submitted")
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        _record_pipeline_stage(stage_number, app_name, status="failed", message=str(exc)[:1000])
        raise
    _record_pipeline_stage(stage_number, app_name, status="completed")
    return result


HEAVY_LOCAL_STAGES = {
    4: "FastTarget",
    10: "InterProScan",
    15: "AlphaFold",
    16: "ColabFold",
    17: "FPocket/P2Rank",
    22: "binders",
    24: "LigQ",
}


def _assert_heavy_stage_allowed(stage, app_name, allow_local_heavy):
    if allow_local_heavy or stage not in HEAVY_LOCAL_STAGES:
        return
    raise RuntimeError(
        f"Refusing to run heavy stage {stage} ({HEAVY_LOCAL_STAGES[stage]}) locally "
        f"while handling {app_name}. Configure a SLURM/remote implementation for this "
        "stage, provide curated data and skip it, or pass --allow-local-heavy explicitly."
    )


def _format_remote_command(template, *, genome, working_dir, folder_path):
    if not template:
        return ""
    return template.format(
        genome=shlex.quote(genome),
        working_dir=shlex.quote(working_dir),
        folder_path=shlex.quote(folder_path),
    )


def _run_configured_remote_stage(stage, app_name, env_prefix, cfg_dict, *, genome, working_dir, folder_path):
    template = os.getenv(f"{env_prefix}_REMOTE_COMMAND", "").strip()
    if not template:
        raise RuntimeError(
            f"{app_name} is configured for SLURM execution but {env_prefix}_REMOTE_COMMAND is not set."
        )
    command = _format_remote_command(
        template,
        genome=genome,
        working_dir=working_dir,
        folder_path=folder_path,
    )
    return _run_python_stage(
        stage,
        app_name,
        run_remote_shell_job,
        cfg_dict,
        env_prefix=env_prefix,
        job_name=f"tpw_{app_name}_{genome}",
        command=command,
        stage_number=stage,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_folder_path(working_dir, genome):
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(working_dir, f"data/{folder_name}/{genome}")


def _read_unips(folder_path, genome):
    with open(os.path.join(folder_path, genome + "_unips.lst"), "r") as f:
        return f.read()


def _run_alphafold_parallel(stage, lines, folder_path, genome):
    """Download AlphaFold models in parallel (network-bound)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(4, len(lines))
    print(f"Downloading {len(lines)} AlphaFold models with {max_workers} workers...")

    def _fetch_one(line):
        _run_stage(stage, "alphafold_unips", alphafold_cmd(line, folder_path, genome))
        return line.split()[1]  # locus_tag

    errors = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, line): line for line in lines}
        for future in as_completed(futures):
            line = futures[future]
            try:
                locus = future.result()
                print(f"  alphafold done: {locus}")
            except Exception as exc:
                errors.append((line, exc))
                print(f"  alphafold FAILED: {line.split()[1] if len(line.split()) > 1 else line}: {exc}")

    if errors:
        failed = ", ".join(l.split()[1] if len(l.split()) > 1 else l for l, _ in errors)
        raise RuntimeError(f"AlphaFold download failed for: {failed}")


def _process_single_protein(args):
    """Process one protein through the full structures chain. Used by the parallel executor."""
    from django.db import connections

    stage, protein, working_dir, folder_path, genome = args
    try:
        alphafold_dir = os.path.join(folder_path, "alphafold")
        print(os.path.join(alphafold_dir, protein, f"{protein}_af.pdb"))
        _run_stage(stage, "load_af_model", load_af_model_cmd(protein, working_dir, folder_path))
        _run_stage(stage, "run_fpocket", run_fpocket_cmd(folder_path, protein))
        _run_stage(stage, "fpocket2json", fpocket2json_cmd(folder_path, protein))
        _run_stage(stage, "load_pocket", load_pocket_cmd(folder_path, protein, working_dir))
        _run_stage(stage, "run_p2rank", run_p2rank_cmd(genome, protein, working_dir))
        _run_stage(stage, "p2rank2json", p2rank2json_cmd(genome, protein, working_dir))
        _run_stage(stage, "load_p2pocket", load_p2pocket_cmd(genome, protein, working_dir))
        return protein
    finally:
        connections.close_all()


def _run_structures_chain(stage, working_dir, folder_path, genome):
    """Replaces the structures_af @join_app: scan PDB files, run per-protein chain."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    alphafold_dir = os.path.join(folder_path, "alphafold")
    if not os.path.isdir(alphafold_dir):
        print("No protein structures found to load.")
        return

    proteins_with_pdb = []
    for locus_tag in sorted(os.listdir(alphafold_dir)):
        pdb_path = os.path.join(alphafold_dir, locus_tag, f"{locus_tag}_af.pdb")
        if os.path.exists(pdb_path) and os.path.getsize(pdb_path) > 0:
            proteins_with_pdb.append(locus_tag)

    if not proteins_with_pdb:
        print("No protein structures found to load.")
        return

    max_workers = min(4, len(proteins_with_pdb))
    print(f"Loading {len(proteins_with_pdb)} structures with {max_workers} workers...")

    tasks = [(stage, p, working_dir, folder_path, genome) for p in proteins_with_pdb]
    errors = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_protein, t): t[1] for t in tasks}
        for future in as_completed(futures):
            protein = futures[future]
            try:
                future.result()
                print(f"  completed: {protein}")
            except Exception as exc:
                errors.append((protein, exc))
                print(f"  FAILED: {protein}: {exc}")

    if errors:
        failed_names = ", ".join(p for p, _ in errors)
        raise RuntimeError(f"Structure processing failed for: {failed_names}")


# ---------------------------------------------------------------------------
# Main genome pipeline
# ---------------------------------------------------------------------------

def run_genome(
    genome,
    gram,
    custom,
    source_genome,
    is_test,
    working_dir,
    cfg_dict,
    start_stage=1,
    skip_stages=None,
    allow_local_heavy=True,
):
    """Run the full 23-stage pipeline for one genome. Raises on any failure.

    start_stage: skip all stages with number < start_stage (used to resume after a failure).
    Stage 1 (clear_folder) is always skipped when start_stage > 1 to preserve existing data.
    skip_stages: optional set of stage numbers to skip even when they are >= start_stage.
    """
    folder_path = _compute_folder_path(working_dir, genome)
    source_accession = (source_genome or genome).strip()
    skip_stages = set(skip_stages or [])

    def _skip(stage):
        return stage < start_stage or stage in skip_stages

    if not _skip(1):
        _run_python_stage(1, "clear_folder", _clear_folder, folder_path)

    if not _skip(2):
        if is_test:
            _run_stage(2, "test_gbk", test_gbk_cmd(working_dir, genome))
        elif custom:
            _run_stage(2, "custom_gbk", custom_gbk_cmd(working_dir, genome, custom))
        else:
            _run_stage(2, "download_gbk", download_gbk_cmd(working_dir, source_accession, target_accession=genome))

    if not _skip(3):
        _run_stage(3, "load_gbk", load_gbk_cmd(working_dir, folder_path, genome))
        _run_stage(3, "sync_genome_metadata", sync_genome_metadata_cmd(working_dir, folder_path, genome))
    if not _skip(4):
        if os.environ.get("TPW_FASTTARGET_USE_REMOTE", "").strip() == "1":
            _run_configured_remote_stage(
                4,
                "fasttarget_remote",
                "TPW_FASTTARGET",
                cfg_dict,
                genome=genome,
                working_dir=working_dir,
                folder_path=folder_path,
            )
        else:
            fasttarget_skip_exec = os.environ.get("TPW_FASTTARGET_SKIP_EXEC", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if not fasttarget_skip_exec:
                _assert_heavy_stage_allowed(4, "fasttarget", allow_local_heavy)
            _run_stage(4, "fasttarget", fasttarget_cmd(working_dir, genome, folder_path))
    if not _skip(5):
        _run_stage(5, "load_score", load_score_cmd(working_dir, genome, "human_offtarget"))
    if not _skip(6):
        _run_stage(6, "load_score", load_score_cmd(working_dir, genome, "micro_offtarget"))
    if not _skip(7):
        _run_stage(7, "load_score", load_score_cmd(working_dir, genome, "essenciality"))
    if not _skip(8):
        _run_stage(8, "index_genome_db", index_db_cmd(working_dir, genome))
    if not _skip(9):
        _run_stage(9, "index_genome_seq", index_seq_cmd(working_dir, genome))
    if not _skip(10):
        if os.environ.get("TPW_INTERPRO_USE_REMOTE", "1").strip() != "1":
            _assert_heavy_stage_allowed(10, "interproscan", allow_local_heavy)
        _run_python_stage(10, "interproscan", run_remote_interproscan,
                          cfg_dict=cfg_dict, folder_path=folder_path, genome=genome)
    if not _skip(11):
        _run_stage(11, "load_interpro", load_interpro_cmd(working_dir, genome, folder_path))
    if not _skip(12):
        _run_stage(12, "gbk2uniprot_map", gbk2uniprot_cmd(working_dir, genome, folder_path))
    if not _skip(13):
        _run_stage(13, "fetch_uniprot_annotations", fetch_annotations_cmd(working_dir, genome, folder_path))
        _run_stage(13, "fetch_experimental_structures", fetch_exp_structures_cmd(working_dir, genome, folder_path))
    if not _skip(14) or not _skip(15):
        protein_list = _run_python_stage(14, "get_unipslst", _read_unips, folder_path, genome)
        if not _skip(15):
            _assert_heavy_stage_allowed(15, "alphafold_unips", allow_local_heavy)
            lines = [l.strip() for l in protein_list.strip().split("\n") if l.strip()]
            if lines:
                _run_alphafold_parallel(15, lines, folder_path, genome)
    if not _skip(16):
        if os.environ.get("TPW_COLABFOLD_USE_REMOTE", "").strip() == "1":
            _run_python_stage(16, "colabfold_predict", run_remote_colabfold,
                              cfg_dict=cfg_dict, folder_path=folder_path, genome=genome)
        else:
            _assert_heavy_stage_allowed(16, "colabfold_predict", allow_local_heavy)
            _run_stage(16, "colabfold_predict", colabfold_cmd(working_dir, genome))
    if not _skip(17):
        if os.environ.get("TPW_STRUCTURES_USE_REMOTE", "").strip() == "1":
            _run_python_stage(
                17,
                "structures_remote",
                run_remote_structures,
                cfg_dict=cfg_dict,
                folder_path=folder_path,
                genome=genome,
                working_dir=working_dir,
            )
        else:
            _assert_heavy_stage_allowed(17, "structures_af", allow_local_heavy)
            _run_structures_chain(17, working_dir, folder_path, genome)
    if not _skip(18):
        _run_stage(18, "druggability_2_csv", druggability_cmd(working_dir, genome))
    if not _skip(19):
        _run_stage(19, "load_score", load_score_cmd(working_dir, genome, "druggability"))
    if not _skip(20):
        _run_stage(20, "psort", psort_cmd(genome, gram))
    if not _skip(21):
        _run_stage(21, "load_score", load_score_cmd(working_dir, genome, "psort"))
    if not _skip(22):
        if os.environ.get("TPW_BINDERS_USE_REMOTE", "").strip() == "1":
            _run_configured_remote_stage(
                22,
                "binders_remote",
                "TPW_BINDERS",
                cfg_dict,
                genome=genome,
                working_dir=working_dir,
                folder_path=folder_path,
            )
        else:
            _assert_heavy_stage_allowed(22, "get_binders", allow_local_heavy)
            _run_stage(22, "get_binders", get_binders_cmd(working_dir, genome))
    if not _skip(23):
        _run_stage(23, "load_binders", load_binders_cmd(working_dir, genome))
    if not _skip(24):
        if os.environ.get("TPW_LIGQ_USE_REMOTE", "").strip() == "1":
            _run_python_stage(24, "ligq_remote", run_remote_ligq,
                              cfg_dict=cfg_dict, folder_path=folder_path, genome=genome)
        else:
            _assert_heavy_stage_allowed(24, "ligq_remote", allow_local_heavy)
            print("LigQ_2 stage 24 skipped: set TPW_LIGQ_USE_REMOTE=1 to enable.")


def _clear_folder(folder_path):
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)


# ---------------------------------------------------------------------------
# CLI entry point — mirrors run_pipeline.py argument handling
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    start = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "genomes",
        help="List of NCBI genomes accession numbers separated with new lines",
        type=str,
        nargs="*",
        default=sys.stdin,
    )
    parser.add_argument("--test", "-t", action="store_true", help="Run in test mode")
    parser.add_argument(
        "--gram",
        choices=["p", "n"],
        default=None,
        help="Specify 'p' for Gram-positive or 'n' for Gram-negative bacteria, optional",
    )
    parser.add_argument("--custom", "-c", default=None, help="Specify the path to the custom GBK file")
    parser.add_argument("--genome-name", default=None, help="Internal genome accession to use for custom uploads")
    parser.add_argument(
        "--start-stage",
        type=int,
        default=1,
        metavar="N",
        help="Resume from stage N, skipping earlier stages (stage 1 always skipped when N>1 to preserve data)",
    )
    parser.add_argument(
        "--skip-stages",
        default="",
        metavar="LIST",
        help="Comma-separated stage numbers to skip in addition to --start-stage.",
    )
    parser.add_argument(
        "--allow-local-heavy",
        action="store_true",
        default=None,
        help="Allow CPU/GPU-heavy stages to run locally. Do not use on login/orchestration nodes.",
    )
    parser.add_argument(
        "--no-local-heavy",
        action="store_true",
        help="Fail instead of running CPU/GPU-heavy stages locally.",
    )

    args = parser.parse_args()
    gram = args.gram
    custom = args.custom
    forbid_local_heavy = os.getenv("TPW_FORBID_LOCAL_HEAVY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    allow_local_heavy = not forbid_local_heavy
    if args.allow_local_heavy is True:
        allow_local_heavy = True
    if args.no_local_heavy:
        allow_local_heavy = False
    skip_stages = set()
    if args.skip_stages.strip():
        try:
            skip_stages = {
                int(part.strip())
                for part in args.skip_stages.split(",")
                if part.strip()
            }
        except ValueError as exc:
            parser.error(f"--skip-stages must be a comma-separated list of integers: {exc}")
    run_specs = []

    if args.test:
        source_genome = "NZ_AP023069.1"
        target_genome = (args.genome_name or source_genome).strip()
        run_specs = [(source_genome, target_genome)]
        gram = "n"
    elif args.custom:
        if args.genome_name:
            target_genome = args.genome_name.strip()
        else:
            _path, file = os.path.split(custom)
            target_genome = file.split(".g")[0]
        run_specs = [(target_genome, target_genome)]
    else:
        if args.genome_name and len(args.genomes) > 1:
            parser.error("--genome-name can only be used with a single genome accession")
        for line in args.genomes:
            source_genome = line.strip().upper()
            if not source_genome:
                continue
            target_genome = (args.genome_name or source_genome).strip()
            run_specs.append((source_genome, target_genome))

    if not run_specs:
        parser.error("No genomes were provided")

    # Read config (only for interproscan_remote SSH settings).
    import configparser

    cfg = configparser.ConfigParser()
    settings_ini = os.path.join(os.path.dirname(__file__), "settings.ini")
    if os.path.exists(settings_ini):
        cfg.read(settings_ini)

    # Resolve working_dir with the same priority as TargetConfig.
    working_dir = (
        os.environ.get("TPW_PIPELINE_WORKING_DIR")
        or (cfg.get("GENERAL", "WorkingDir", fallback=None))
        or os.getcwd()
    )

    _initialize_pipeline_run(run_specs, gram, custom, args.test)
    internal_genomes = [target for _, target in run_specs]

    exit_status = "finished"
    run_error = None
    try:
        for source_genome, target_genome in run_specs:
            run_genome(
                genome=target_genome,
                gram=gram,
                custom=custom,
                source_genome=source_genome,
                is_test=args.test,
                working_dir=working_dir,
                cfg_dict=cfg,
                start_stage=args.start_stage,
                skip_stages=skip_stages,
                allow_local_heavy=allow_local_heavy,
            )

    except Exception as exc:
        exit_status = "failed"
        run_error = exc
        raise
    finally:
        end = time.time()
        runtime = end - start

        run_id = _pipeline_run_id()
        if run_id is not None:
            try:
                from tpweb.services.pipeline_runs import finalize_pipeline_run

                final_status = "finished" if exit_status == "finished" else "failed"
                finalize_pipeline_run(
                    run_id,
                    status=final_status,
                    error_message=_safe_error_text(run_error) if run_error else "",
                )
            except Exception:
                pass

        _write_last_run_marker(
            status=exit_status,
            genomes=internal_genomes,
            start_ts=start,
            end_ts=end,
            gram=gram,
            custom=custom,
            error=run_error,
        )
        print(runtime)

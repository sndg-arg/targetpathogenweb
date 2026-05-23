import argparse
import json
import os
import sys
import time
from functools import partial
from datetime import datetime, timezone

import parsl
from parsl import join_app

from config import TargetConfig
from apps import (
    clear_folder, download_gbk, test_gbk, custom_gbk, load_gbk, sync_genome_metadata,
    fasttarget, load_score, index_genome_db, index_genome_seq,
    interproscan, load_interpro, gbk2uniprot_map, fetch_uniprot_annotations,
    get_unipslst, alphafold_unips, esmfold_predict, structures_af,
    druggability_2_csv, psort, get_binders, load_binders,
)


def _pipeline_shared_dir():
    default_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "parsl")
    )
    return os.environ.get("TPW_PIPELINE_SHARED_DIR", default_dir)


def _marker_paths():
    shared_marker_path = os.path.join(_pipeline_shared_dir(), "last_pipeline_run.json")
    legacy_marker_path = os.path.join(os.path.dirname(__file__), "last_pipeline_run.json")
    marker_paths = []
    for candidate in (shared_marker_path, legacy_marker_path):
        normalized = os.path.normpath(candidate)
        if normalized not in marker_paths:
            marker_paths.append(normalized)
    return marker_paths


def _write_last_run_marker(
    status,
    genomes,
    start_ts,
    end_ts,
    gram=None,
    custom=None,
    error=None,
):
    payload = {
        "status": status,
        "genomes": genomes,
        "gram": gram,
        "custom": custom,
        "started_at_utc": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "finished_at_utc": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
        "runtime_seconds": round(max(0.0, end_ts - start_ts), 3),
    }
    if error:
        payload["error"] = _safe_error_text(error)

    for marker_path in _marker_paths():
        try:
            os.makedirs(os.path.dirname(marker_path), exist_ok=True)
            with open(marker_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
        except Exception:
            # Marker is best-effort metadata; do not fail the run because of write issues.
            pass


def _safe_error_text(error):
    if error is None:
        return None
    try:
        return str(error)
    except Exception:
        try:
            return repr(error)
        except Exception:
            return f"{type(error).__name__} (unprintable)"


def _pipeline_run_id():
    raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _record_pipeline_stage(stage_number, app_name, *, task_id=None, status="info", message="", payload=None):
    run_id = _pipeline_run_id()
    if run_id is None:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            run_id,
            stage_number=stage_number,
            app_name=app_name,
            task_id=task_id,
            status=status,
            message=message,
            payload=payload,
        )
    except Exception:
        pass


def _track_future(future, stage_number, app_name):
    if future is None:
        return None

    task_id = getattr(future, "tid", None)
    _record_pipeline_stage(
        stage_number,
        app_name,
        task_id=task_id,
        status="submitted",
    )

    def _on_done(done_future, *, stage_number, app_name, task_id):
        try:
            error = done_future.exception()
        except Exception as exc:
            error = exc
        if error is None:
            _record_pipeline_stage(
                stage_number,
                app_name,
                task_id=task_id,
                status="completed",
            )
        else:
            _record_pipeline_stage(
                stage_number,
                app_name,
                task_id=task_id,
                status="failed",
                message=_safe_error_text(error),
            )

    future.add_done_callback(
        partial(_on_done, stage_number=stage_number, app_name=app_name, task_id=task_id)
    )
    return future


def _initialize_pipeline_run(run_specs, gram, custom, is_test):
    run_id = _pipeline_run_id()
    if run_id is not None:
        return run_id

    if not os.getenv("DJANGO_SETTINGS_MODULE"):
        return None

    try:
        from tpweb.services.pipeline_runs import create_pipeline_run, mark_pipeline_run_started
    except Exception:
        return None

    upload_id_raw = str(os.getenv("TPW_GENOME_UPLOAD_ID") or "").strip()
    upload_id = None
    if upload_id_raw:
        try:
            upload_id = int(upload_id_raw)
        except (TypeError, ValueError):
            upload_id = None

    source_genome, target_genome = run_specs[0]
    run = create_pipeline_run(
        genome_upload_id=upload_id,
        internal_accession=target_genome,
        source_accession=source_genome,
        gram=gram or "",
        custom_input=custom or "",
        run_log_path=str(os.getenv("TPW_PIPELINE_LOG_PATH") or ""),
        metadata={
            "genomes": [target for _, target in run_specs],
            "source_genomes": [source for source, _ in run_specs],
            "test": bool(is_test),
        },
    )
    os.environ["TPW_PIPELINE_RUN_ID"] = str(run.id)
    mark_pipeline_run_started(
        run.id,
        pid=os.getpid(),
        run_log_path=str(os.getenv("TPW_PIPELINE_LOG_PATH") or ""),
    )
    _record_pipeline_stage(
        None,
        "run_pipeline",
        status="running",
        message="Pipeline process started.",
    )
    return run.id

@join_app
def scatter_alphafold(protein_list_text, folder_path, genome):
    """Scatter AlphaFold downloads across proteins. This is a @join_app so
    Parsl manages the dependency wait without blocking the HTEX executor.
    Note: Parsl auto-resolves futures passed to @join_app, so protein_list_text
    is already a string by the time this function runs."""
    futures = []
    for line in protein_list_text.split('\n'):
        if line.strip():
            r = _track_future(
                alphafold_unips(protein_list=line, folder_path=folder_path, genome=genome, inputs=[]),
                15,
                "alphafold_unips",
            )
            futures.append(r)
    return futures


@join_app
def run(genome, gram, custom, source_genome=None, is_test=False):
    import math
    import os

    cfg = TargetConfig()
    cfg_dict = cfg.get_config_dict()
    working_dir = cfg_dict.get("GENERAL", "WorkingDir")
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = os.path.join(working_dir, f"data/{folder_name}/{genome}")
    source_accession = (source_genome or genome).strip()

    r_clear = _track_future(clear_folder(folder_path=folder_path, inputs = []), 1, "clear_folder")
    if is_test:
        r_down = _track_future(test_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear]), 2, "test_gbk")
    elif custom:
        r_down = _track_future(
            custom_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear], custom=custom),
            2,
            "custom_gbk",
        )
    else:
        r_down = _track_future(
            download_gbk(
                working_dir=working_dir,
                genome=source_accession,
                target_accession=genome,
                inputs=[r_clear],
            ),
            2,
            "download_gbk",
        )
    r_load = _track_future(
        load_gbk(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_down]),
        3,
        "load_gbk",
    )
    r_metadata = _track_future(
        sync_genome_metadata(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_load]),
        3,
        "sync_genome_metadata",
    )
    # ===================================================================
    # DAG: 5 parallel branches after load_gbk, with real dependencies
    # ===================================================================
    #
    #                 ┌→ fasttarget → [load_human, load_micro, load_essen]
    #                 │
    # load_gbk ──────┼→ index_db → index_seq → interproscan → load_interpro
    #                 │
    #                 ├→ gbk2uniprot ┬→ fetch_uniprot_annotations
    #                 │              ├→ get_unipslst → alphafold → esmfold
    #                 │              │    → structures → druggability → load_drug
    #                 │              └→ get_binders → load_binders
    #                 │
    #                 └→ psort → load_psort
    #
    # Pipeline is done when ALL terminal futures complete.
    # ===================================================================

    # --- Branch A: Scoring (fasttarget + 3 parallel score loads) ---
    r_fasttarget = _track_future(
        fasttarget(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_metadata]),
        4,
        "fasttarget",
    )
    load_human_offt = _track_future(
        load_score(working_dir=working_dir, genome=genome, inputs=[r_fasttarget], param='human_offtarget'),
        5,
        "load_score",
    )
    load_micro_offt = _track_future(
        load_score(working_dir=working_dir, genome=genome, inputs=[r_fasttarget], param='micro_offtarget'),
        6,
        "load_score",
    )
    load_essen = _track_future(
        load_score(working_dir=working_dir, genome=genome, inputs=[r_fasttarget], param='essenciality'),
        7,
        "load_score",
    )

    # --- Branch B: Indexing → InterProScan (needs load_gbk only) ---
    r_index_db = _track_future(
        index_genome_db(working_dir=working_dir, inputs=[r_metadata], genome=genome),
        8,
        "index_genome_db",
    )
    r_index_seq = _track_future(
        index_genome_seq(working_dir=working_dir, inputs=[r_index_db], genome=genome),
        9,
        "index_genome_seq",
    )
    r_interpro = _track_future(
        interproscan(cfg_dict=cfg_dict, folder_path=folder_path, genome=genome, inputs=[r_index_seq]),
        10,
        "interproscan",
    )
    r_load_interpro = _track_future(
        load_interpro(working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_interpro]),
        11,
        "load_interpro",
    )

    # --- Branch C: UniProt mapping → structures → druggability ---
    # gbk2uniprot only needs bioentries in DB (from load_gbk), not interpro
    r_gbk2uniprot = _track_future(
        gbk2uniprot_map(working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_metadata]),
        12,
        "gbk2uniprot_map",
    )
    # fetch_uniprot_annotations and get_unipslst both read _unips.lst → parallel
    r_uniprot_annotations = _track_future(
        fetch_uniprot_annotations(working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_gbk2uniprot]),
        13,
        "fetch_uniprot_annotations",
    )
    protein_list = _track_future(
        get_unipslst(folder_path=folder_path, genome=genome, inputs=[r_gbk2uniprot]),
        14,
        "get_unipslst",
    )
    r_alphafolds = scatter_alphafold(protein_list, folder_path=folder_path, genome=genome)
    r_esmfold = _track_future(
        esmfold_predict(
            working_dir=working_dir,
            genome=genome,
            folder_path=folder_path,
            inputs=[r_alphafolds],
        ),
        16,
        "esmfold_predict",
    )
    r_stru = _track_future(
        structures_af(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_esmfold]),
        17,
        "structures_af",
    )
    d_2_csv = _track_future(
        druggability_2_csv(working_dir=working_dir, genome=genome, inputs=[r_stru]),
        18,
        "druggability_2_csv",
    )
    load_d = _track_future(
        load_score(working_dir=working_dir, genome=genome, inputs=[d_2_csv], param='druggability'),
        19,
        "load_score",
    )

    # --- Branch D: Localization (only needs genome loaded) ---
    p_run = _track_future(psort(genome=genome, gram=gram, inputs=[r_load]), 20, "psort")
    load_p = _track_future(
        load_score(working_dir=working_dir, genome=genome, inputs=[p_run], param='psort'),
        21,
        "load_score",
    )

    # --- Branch E: Binders (needs _unips.lst from gbk2uniprot) ---
    get_b = _track_future(get_binders(working_dir=working_dir, genome=genome, inputs=[r_gbk2uniprot]), 22, "get_binders")
    load_b = _track_future(load_binders(working_dir=working_dir, genome=genome, inputs=[get_b]), 23, "load_binders")

    # Pipeline done when ALL branches complete
    return [load_human_offt, load_micro_offt, load_essen,  # Branch A
            r_load_interpro,                                # Branch B
            r_uniprot_annotations, load_d,                  # Branch C
            load_p,                                         # Branch D
            load_b]                                         # Branch E

if __name__ == "__main__":
    start = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument('genomes', help="List of NCBI genomes accession numbers separated with new lines",
                        type=str,
                        nargs='*',
                        default=sys.stdin)
    parser.add_argument('--test', '-t', action='store_true', help="Run in test mode")
    parser.add_argument('--gram', choices=['p', 'n'], default=None, help="Specify 'p' for Gram-positive or 'n' for Gram-negative bacteria, optional")
    parser.add_argument('--custom','-c', default=None, help="Specify the path to the custom GBK file")
    parser.add_argument('--genome-name', default=None, help="Internal genome accession to use for custom uploads")

    args = parser.parse_args()
    gram = args.gram
    custom = args.custom
    run_specs = []

    if args.test:
        source_genome = 'NZ_AP023069.1'
        target_genome = (args.genome_name or source_genome).strip()
        run_specs = [(source_genome, target_genome)]
        gram = 'n'
    elif args.custom:
        if args.genome_name:
            target_genome = args.genome_name.strip()
        else:
            path, file = os.path.split(custom)
            target_genome = file.split(".g")[0]
        run_specs = [(target_genome, target_genome)]
    else:
        if args.genome_name and len(args.genomes) > 1:
            parser.error("--genome-name can only be used with a single genome accession")
        for l in args.genomes:
            source_genome = l.strip().upper()
            if not source_genome:
                continue
            target_genome = (args.genome_name or source_genome).strip()
            run_specs.append((source_genome, target_genome))

    if not run_specs:
        parser.error("No genomes were provided")

    cfg = TargetConfig("settings.ini")
    _initialize_pipeline_run(run_specs, gram, custom, args.test)
    parsl.load(cfg.get_parsl_cfg())
    parsl.set_stream_logger()
    results = list()
    internal_genomes = [target for _, target in run_specs]

    exit_status = "finished"
    run_error = None
    try:
        for source_genome, target_genome in run_specs:
            r = run(
                genome=target_genome,
                gram=gram,
                custom=custom,
                source_genome=source_genome,
                is_test=args.test,
            )
            results.append(r)
        for r in results:
            r.result()
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
        try:
            dfk = parsl.dfk()
        except Exception:
            dfk = None
        if dfk is not None:
            try:
                dfk.cleanup()
            except Exception:
                pass
        try:
            parsl.clear()
        except Exception:
            pass
        print(runtime)

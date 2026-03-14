import parsl
from parsl import join_app
from config import *
from apps import *
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


def _marker_path():
    import os
    return os.path.join(os.path.dirname(__file__), "last_pipeline_run.json")


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

    try:
        with open(_marker_path(), "w", encoding="utf-8") as handle:
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

@join_app
def run(genome, gram, custom, source_genome=None):
    import math
    import os

    cfg = TargetConfig()
    cfg_dict = cfg.get_config_dict()
    working_dir = cfg_dict.get("GENERAL", "WorkingDir")
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = os.path.join(working_dir, f"data/{folder_name}/{genome}")
    source_accession = (source_genome or genome).strip()

    r_clear = clear_folder(folder_path=folder_path, inputs = [])
    if args.test:
        r_down = test_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear])
    elif args.custom:
        r_down = custom_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear], custom=custom)
    else:
        r_down = download_gbk(
            working_dir=working_dir,
            genome=source_accession,
            target_accession=genome,
            inputs=[r_clear],
        )
    r_load = load_gbk(working_dir=working_dir,
                      folder_path=folder_path, genome=genome, inputs=[r_down])
    r_fasttarget = fasttarget(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_load])
    load_human_offt = load_score(working_dir=working_dir, genome=genome, inputs=[r_fasttarget], param = 'human_offtarget')
    load_micro_offt = load_score(working_dir=working_dir, genome=genome, inputs=[load_human_offt], param = 'micro_offtarget')
    load_essen = load_score(working_dir=working_dir, genome=genome, inputs=[load_micro_offt], param = 'essenciality')
    r_index_db = index_genome_db(working_dir=working_dir, inputs=[
                                 load_essen], genome=genome)
    r_index_seq = index_genome_seq(working_dir=working_dir, inputs=[
                                   r_index_db], genome=genome)
    r_interpro = interproscan(cfg_dict=cfg_dict, folder_path=folder_path, genome=genome, inputs=[r_index_seq])
    r_load_interpro = load_interpro(
        working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_interpro])
    r_gbk2uniprot = gbk2uniprot_map(
        working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_load_interpro])
    protein_list = get_unipslst(
        folder_path=folder_path, genome=genome, inputs=[r_gbk2uniprot])
    r_alphafolds = list()
    for proteins in (protein_list.result()).split('\n'):
        if len(proteins) > 0:
            r = alphafold_unips(protein_list=proteins, folder_path=folder_path,
                            genome=genome, inputs=[protein_list])
            r_alphafolds.append(r)
    
    r_stru = strucutures_af(
        working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=r_alphafolds)
    
    d_2_csv = druggability_2_csv(working_dir=working_dir, genome=genome, inputs =[r_stru])

    load_d = load_score(working_dir=working_dir, genome=genome, inputs=[d_2_csv], param = 'druggability')
    
    p_run = psort(genome= genome, gram= gram, inputs=[load_d])

    load_p = load_score(working_dir=working_dir, genome=genome, inputs=[p_run], param = 'psort')
    
    get_b = get_binders(working_dir=working_dir, genome=genome, inputs=[load_p])

    load_b = load_binders(working_dir=working_dir, genome=genome, inputs=[get_b])

    return load_b

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

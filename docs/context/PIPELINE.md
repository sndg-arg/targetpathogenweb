# Pipeline internals

Moved out of `CLAUDE.md` so it only loads when needed.

## Pipeline architecture
- **Orchestrator**: `pipeline/run_pipeline_direct.py` — direct subprocess, no Parsl
- **Commands**: `pipeline/pipeline_commands.py` — one function per stage returning a bash command string
- **Activation**: `TPW_USE_DIRECT_PIPELINE=1` env var selects the new orchestrator
- **Legacy**: `pipeline/apps.py`, `pipeline/config.py`, `pipeline/run_pipeline.py` — old Parsl code, kept as fallback, do not modify
- **23 stages**, mostly linear — any failure raises immediately (no silent partial failures)
- **Remote stages**: stage 10 (InterProScan via `interproscan_remote.py`), optionally stage 4 (FastTarget via `fasttarget_remote.py`) and stage 16 (ColabFold via `colabfold_remote.py`) run on SLURM cluster nodes over SSH
- **Parallelized stages**: stage 15 (AlphaFold downloads, 4 workers) and stage 17 (structure processing, 4 workers) use `ThreadPoolExecutor`. All other stages run sequentially.
- **Stage events** tracked in `PipelineStageEvent` model (submitted → completed/failed)
- **Status**: `tpweb/services/pipeline_status.py` — reads from `PipelineRun` as source of truth
- **Orphaned-run reconciliation**: `tpweb/services/genome_upload_status.py:reconcile_genome_uploads`
  (polled every cycle by `tpweb_process_genome_queue`) auto-fails a `PipelineRun` stuck on
  `status=running` with no update for `STALE_PIPELINE_RUN_GRACE_SECONDS` (24h) — covers the
  orchestrator dying without reaching its own cleanup (queue container restart/OOM, a hung
  remote SSH call). Without this, a dead run can sit "running" indefinitely with the Genomes
  list quietly missing data the whole time, since the queue worker refuses to pick up a new
  job for the same genome while one is still marked running. `tpweb/services/pipeline_runs.py:
  cancel_pipeline_run` escalates to SIGKILL after a 2s grace period if SIGTERM didn't actually
  stop the process — never run the manual reset shell snippet below against a genome whose
  pipeline might still be alive; check `ps aux | grep run_pipeline_direct` in `queue` first.
  Runs launched straight from the orchestrator CLI (no `GenomeUpload`) are failed by the same
  24h rule (`fail_stale_unlinked_pipeline_runs`). `create_pipeline_run` refuses a second active
  run for the same genome; free it with `python manage.py cancel_pipeline_run <id>` (does not
  signal the recorded PID unless `--kill` is passed — the PID is container-local).

## Pipeline stages overview
1. clear_folder → download/test/custom gbk → load_gbk
2. fasttarget → load_score (×3: human_offtarget, micro_offtarget, essenciality)
3. index_genome_db → index_genome_seq → interproscan (remote SSH) → load_interpro
4. gbk2uniprot_map → fetch_uniprot_annotations → alphafold loop → colabfold (local CPU or remote GPU) → structures chain → load_uniprot_sites → druggability → load_score
5. psort → load_score
6. get_binders → load_binders

## PSORTb
Runs via Docker-in-Docker (`/var/run/docker.sock` mounted). Has fallback to `tpweb_psort_fallback` management command when Docker is unavailable.

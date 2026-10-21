# Remote SLURM stages

Moved out of `CLAUDE.md` so it only loads when needed.

## FastTarget (off-target/essentiality)
- **Stage 4**, controlled by `TPW_FASTTARGET_USE_REMOTE`:
  - `0` (default): runs `fasttarget.py` locally via `fast_command` — blocked by the
    heavy-stage guard on Nodo0 (a shared orchestration node, not a compute node)
    unless `--allow-local-heavy` is passed explicitly.
  - `1`: runs on a remote SLURM CPU node via `pipeline/fasttarget_remote.py`. **One
    SLURM job per genome** (both the BLAST/DIAMOND search and FastTarget's own
    result parsing run in that one job).
- **Why this one's different from InterProScan/ColabFold/LigQ_2**: those tools live
  on the SLURM cluster already (conda envs, GPUs, huge reference DBs). FastTarget
  doesn't — it's vendored in this repo (`fasttarget/`) and normally runs inside the
  web/queue container itself, with self-downloading reference DBs under
  `/app/fasttarget/databases`. The remote path instead reuses the fact that the two
  functions Target actually calls (`human_offtarget`/`gut_microbiome_offtarget` via
  `fasttarget/ftscripts/offtargets.py`, essentiality via `essentiality.py`) only wrap
  plain `blastp`/`diamond blastp` — no Docker/Singularity involved (that's only used
  by unrelated optional FastTarget features Target's `fast_command.py` never enables:
  foldseek, roary, psortb, corecruncher).
- **One-time cluster setup** (not automated, do once per cluster):
  1. Copy the repo's `fasttarget/` directory to the cluster (e.g. `~/fasttarget`).
  2. `conda env create -f fasttarget/requirements.yml` (creates a `fasttarget` env
     with `blast=2.17.0` + `diamond=2.1.18` already pinned — nothing else to install).
     If conda's shared pkg cache isn't writable, set `CONDA_PKGS_DIRS` to a directory
     under your own home first.
  3. Bootstrap the reference DBs via SLURM (never on the login/head node):
     `sbatch` a job running `python fasttarget/databases.py --download all
     --database-path ~/fasttarget_databases --cpus 4` inside the `fasttarget` env.
- **Flow**: dump proteome FASTA from the DB (`dump_genome_proteins_fasta`, the same
  command LigQ_2 uses) → SCP FASTA + the genome's GBK to the cluster → one SLURM job
  runs `ftscripts.offtargets`/`essentiality`'s own search+parse functions directly
  (human off-target BLAST, DEG BLAST, gut-microbiome-catalogue DIAMOND, then their
  own TSV parsing — reused unmodified) → tar-pipe the small `offtarget`/`essentiality`
  output dirs back → `fast_command` runs locally with `TPW_FASTTARGET_SKIP_EXEC=1` +
  `TPW_FASTTARGET_ORGANISM_DIR` pointed at the copied-back output, so Target's own
  DB-loading logic runs unchanged and `fasttarget.py` itself never runs a second time.
- **Config** (env vars, all have defaults, same `SSH_HOSTNAME`/`SSH_USERNAME`/
  `SSH_WORKDIR` as the other remote stages):
  - `TPW_FASTTARGET_USE_REMOTE=1` — activate remote mode
  - `TPW_FASTTARGET_CONDA_PREFIX` — default `/home/shared/miniconda3.8`
  - `TPW_FASTTARGET_CONDA_ENV` — default `fasttarget` (a named env, not a prefix path)
  - `TPW_FASTTARGET_REMOTE_DIR` — default `/home/agutson/fasttarget`
  - `TPW_FASTTARGET_REMOTE_DATABASES_DIR` — default `/home/agutson/fasttarget_databases`
  - `TPW_FASTTARGET_SLURM_PARTITION` — default `cpu`
  - `TPW_FASTTARGET_SLURM_TIME` — default `02:00:00`
  - `TPW_FASTTARGET_SLURM_MEM` — default `8G`
  - `TPW_FASTTARGET_SLURM_CPUS` — default `4`
  - `TPW_FASTTARGET_REMOTE_POLL_SEC` — default `30`
  - `TPW_FASTTARGET_REMOTE_WAIT_SEC` — default `21600` (6h)

## PSORTb (stage 20)

- Cluster Compose defaults to `TPW_PSORT_USE_REMOTE=1` for web and queue. Stage 20
  is now blocked by `--no-local-heavy` unless remote mode is enabled. Nodo0 only
  transfers FASTA/TSV and loads scores; all PSORT/BLAST work runs inside SLURM.
- One-time setup on the cluster: copy `scripts/cluster/setup_psort.sh`, then run
  `sbatch setup_psort.sh`. It installs Apptainer into a separate user environment,
  pulls `brinkmanlab/psortb_commandline:1.0.2` as a SIF and tests execution. If user
  namespaces are disabled, the cluster administrator must provide a supported
  container runtime; the script does not alter kernel settings or use sudo.
- `TPW_PSORT_APPTAINER_BIN` and `TPW_PSORT_IMAGE` default under `SSH_WORKDIR` to
  `work/conda_envs/tpw_apptainer/bin/apptainer` and `tpw_images/psortb_1.0.2.sif`.
  `TPW_PSORT_REMOTE_SETUP` optionally loads modules/environment before the job.
  `TPW_PSORT_REMOTE_PYTHON` defaults to the Python 3.10 interpreter installed in
  the same `tpw_apptainer` environment, avoiding dependence on system Python.
  Setup uses `$HOME` by default; override the same paths if `SSH_WORKDIR` differs.
- One SLURM job, four parallel 50-protein batches by default. Each container gets
  isolated `/tmp`; FASTA sequences are preserved. The SCLBlast diagnostic reports
  the query ID if BioPerl returns no BLAST result, without suppressing the error.
- Complete batches are cached under `SSH_WORKDIR/tpw_psort/cache`, keyed by input,
  Gram type, batch size, image contents and worker code. Resume from stage 20
  reuses validated batches. Failed batches keep input, raw output and logs.
- Stage 20 requires successful SLURM exit plus a completion marker, downloads to
  a temporary file and validates exact protein coverage before replacing
  `psort.tsv`. Fatal messages, malformed headers, missing/duplicate proteins and
  invalid localizations fail the stage, even if PSORT exits 0. Stage 21 validates
  again when resumed directly, before any score loading.
- Tune `TPW_PSORT_SLURM_CPUS` (workers), `TPW_PSORT_BATCH_SIZE`,
  `TPW_PSORT_BATCH_TIMEOUT_SEC` (per batch), and the usual `TPW_PSORT_SLURM_*` /
  `TPW_PSORT_REMOTE_*` variables; see `.env.cluster.example`. Defaults: 4 CPU,
  16G, four-hour job, 24-hour submission-to-completion wait, 30-second polls.
- With `TPW_LIGQ_USE_REMOTE=1`, direct orchestration also omits stages 22/23 unless
  a separate remote binders stage is explicitly enabled, matching the curated
  recovery flow. LigQ stage 24 loads binder evidence directly.
- Explicitly authorized nodo0 recovery only: run
  `TPW_ALLOW_NODO0_PSORT=1 bash scripts/cluster/recover_psort_nodo0.sh public__ACCESSION n`
  on the host. It uses the existing Docker image in two parallel, isolated batches
  (each limited to one CPU and 2 GiB), keeps checkpoints and validates all proteins
  before continuing stage 21 and remote LigQ. No queue rebuild/restart is needed;
  stages 22/23 are explicitly skipped. A host lock prevents concurrent recoveries,
  and the script refuses to start while a pipeline is running. Cluster defaults
  remain remote; this exception does not change `.env` or disable heavy-stage guards.
- If user namespaces block Apptainer, `scripts/cluster/probe_psort_udocker.sh`
  tests udocker 1.3.17 in PRoot mode P1 via SLURM, in a separate user venv/repository.
  It only checks PSORT startup and SCLBlast module loading; this is an experimental
  alternative, not an enabled pipeline backend or proof of full prediction support.
- After that probe passes, submit the actual 50-protein prediction test from nodo0:
  `bash scripts/cluster/test_psort_udocker.sh public__ACCESSION n tpw_psort_probe_JOBID`.
  The helper prepares unique remote input/validator files, prints the submitted ID,
  and requires exact coverage and valid localizations before reporting success.
  It does not load scores or modify an active pipeline/recovery.

## InterProScan
Runs remotely over SSH on the QB cluster. Config in `pipeline/settings.ini` (SSH vars).
Uses `-b output_prefix` flag (not `-o`/`-d` — they're mutually exclusive in v5.62).
conda env: `interproscan`. Key fix: `set -u` must come AFTER `conda activate`.
- Stage 10 can legitimately stay active for hours. First check SLURM state before assuming the pipeline is stuck.
- On cluster, the real source of truth is the remote SLURM job (`squeue` / `sacct` on `cluster.qb.fcen.uba.ar`), not the local Django banner.
- If `slurm-<jobid>.out` exists and shows `% completed`, InterProScan is healthy even if the UI still says stage 10.
- **NODE_FAIL auto-retry**: a SLURM compute node crashing mid-job (hardware/scheduler
  fault, not an app bug) is handled automatically — `pipeline/interproscan_remote.py`
  resubmits the same job up to `TPW_INTERPRO_NODE_FAIL_RETRIES` times (default 2) before
  failing the stage. A stage-10 `info` event logs each resubmission with its new job id.

## ColabFold
- **Two execution modes** for stage 16, controlled by `TPW_COLABFOLD_USE_REMOTE`:
  - `0` (default): runs locally on CPU inside `target2_nodo0_queue` via `colabfold_predict` management command. Extremely slow (~30–60 min per protein).
  - `1`: runs remotely on SLURM nodes via `pipeline/colabfold_remote.py`. **One SLURM job per protein** by default, so one failure doesn't kill the rest; optionally batched first (`TPW_COLABFOLD_BATCH_SIZE`, below).
- **Remote mode runs in two passes** (`run_remote_colabfold`), not one combined loop — this split exists because remote-CPU ColabFold can take many hours for a single hard/long protein, and inline retry used to tie up a whole worker thread for that entire time, starving the rest of the genome of GPU concurrency (one bad protein could make ~5000 others crawl):
  0. **Batched GPU pass** (only when `TPW_COLABFOLD_BATCH_SIZE` > 1): GPU-eligible proteins sorted by length, chunked, one SLURM GPU job per chunk (concurrency `TPW_COLABFOLD_MAX_PARALLEL`). Measured on the cluster, a one-protein job spent ~45s on real GPU work out of ~4-5 min per protein — the rest was SLURM queueing, conda/ColabFold startup, model recompilation and the 60s poll interval, all paid once per batch instead. A batch runs `colabfold_batch ... || echo` so one aborting query keeps the rest; the batch's PDBs are matched back by exact `<tag>_(un)relaxed_rank_001` name (`_find_batch_pdb` — a plain prefix match would let `X_1` grab `X_1_2`'s file in a shared dir). Anything a batch didn't produce (whole job failed, bad node, query aborted) falls through to pass 1 unchanged.
  1. **GPU-fast pass**: one SLURM GPU job per protein <= `TPW_COLABFOLD_MAX_SEQ_LENGTH`, concurrency `TPW_COLABFOLD_MAX_PARALLEL`. A protein that's too long for GPU, or whose GPU attempt(s) all fail, is *deferred* — nothing in this pass ever waits on a CPU job.
  2. **CPU catch-up pass**: runs only after the GPU pass fully finishes, over exactly the deferred proteins, with its own concurrency (`TPW_COLABFOLD_CPU_MAX_PARALLEL`, defaults to the same value as `TPW_COLABFOLD_MAX_PARALLEL`). Isolated on purpose so it can't block the fast pass.
  - `TPW_COLABFOLD_STRICT=1` makes a GPU failure a hard failure for that protein instead of deferring it to the CPU pass (that protein ends up with no structure; stage 16 itself still finishes and reports every such failure at the end, it does not abort on the first one).
  - Persists `job_id` and `remote_job_dir` in `PipelineRun` per attempt. On timeout/failure, does `scancel` to avoid orphan GPU jobs.
  - **SSH outages are ridden out, not treated as job failures**: a dropped/unreachable connection (`_is_connection_error`) reconnects and keeps polling the same SLURM job, and opening a session waits up to `TPW_COLABFOLD_SSH_OUTAGE_WAIT_SEC` (default 21600). Before this, a few minutes of cluster SSH downtime one night failed every in-flight and queued batch in the same minute (5074 proteins dumped back to the per-protein pass). Job-side failures/timeouts raise `ColabFoldJobError` so they're never mistaken for a network timeout (`socket.timeout` *is* `TimeoutError` in 3.10).
  - **Every stage-16 start first recovers orphaned outputs** (`_recover_remote_outputs`): rank_001 PDBs an interrupted run's jobs finished on the cluster but never copied back are pulled into the workspace before anything is resubmitted.
- **Remote config** (env vars, all have defaults):
  - `TPW_COLABFOLD_USE_REMOTE=1` — activate remote mode
  - `TPW_COLABFOLD_CONDA_PREFIX` — default `/home/shared/miniconda3.8`
  - `TPW_COLABFOLD_CONDA_ENV` — default `colabfold`
  - `TPW_COLABFOLD_MAX_SEQ_LENGTH` — default `800` (safe for 8 GB VRAM GPUs like RTX 2080) — raising it reduces how often the CPU catch-up pass is needed, but only safe if the cluster's GPUs actually have enough VRAM headroom for longer sequences
  - `TPW_COLABFOLD_MAX_PARALLEL` — default `8` (GPU-fast pass concurrency)
  - `TPW_COLABFOLD_BATCH_SIZE` — default `1` (no batch pass). ~25 is a reasonable value; the public MSA server's rate limit (`Sleeping for Ns. Reason: RATELIMIT` in a job's `output/log.txt`) is then the next ceiling. Progress in the `alphafold/` dir jumps a batch at a time rather than one protein at a time
  - `TPW_COLABFOLD_CPU_MAX_PARALLEL` — default: same as `TPW_COLABFOLD_MAX_PARALLEL`. CPU jobs are heavier per-worker (`TPW_COLABFOLD_CPU_CPUS`/`TPW_COLABFOLD_CPU_MEM` below), so this exists to cap catch-up concurrency independently
  - `TPW_COLABFOLD_PARTITION` — default `gpu`; `TPW_COLABFOLD_CPU_PARTITION` — default `cpu`
  - `TPW_COLABFOLD_GRES` — default `gpu:1`
  - `TPW_COLABFOLD_TIME` — default `12:00:00` (per GPU job); `TPW_COLABFOLD_CPU_TIME` — default `24:00:00` (per CPU catch-up job — generous on purpose, a single long protein can legitimately take many hours on CPU)
  - `TPW_COLABFOLD_MEM` — default `16gb`; `TPW_COLABFOLD_CPU_MEM` — default `32gb`
  - `TPW_COLABFOLD_CPUS` — default `4`; `TPW_COLABFOLD_CPU_CPUS` — default `8`
  - `TPW_COLABFOLD_GPU_RETRIES` — default `1`; `TPW_COLABFOLD_CPU_RETRIES` — default `2`
  - `TPW_COLABFOLD_EXCLUDE` — exclude specific bad SLURM nodes (same idea as InterProScan's node exclusion); `TPW_COLABFOLD_CPU_EXCLUDE` overrides it for the CPU partition specifically if set
  - `TPW_COLABFOLD_NUM_RECYCLES` — default `3`; `TPW_COLABFOLD_NUM_MODELS` — default `1`
- **Whole-pipeline timeout matters here**: `TPW_PIPELINE_TIMEOUT_SEC` (`tpweb/services/genome_uploads.py`, default 6h, commonly overridden much higher — e.g. 86400/24h) is the *entire run's* ceiling, not per-stage. A genome with thousands of missing structures can legitimately need far longer than 24h for stage 16 alone; if the orchestrator hits this timeout mid-stage-16 it gets SIGTERM'd (escalating to SIGKILL), the whole run fails, and reconcile_genome_uploads' 24h staleness check (see above) is what actually surfaces that failure in the UI since the killed process never reaches its own cleanup. Size this to the genome, not just "a day."
- **Local mode progress** (when `TPW_COLABFOLD_USE_REMOTE=0`):
  - `run_pipeline_direct.py` executes `colabfold_predict` with `capture_output=True`, so live progress does NOT appear in `docker logs`.
  - Real progress is in `/tmp/colabfold_*/output/log.txt` inside the queue container.
  - Output is written to a temp dir first and copied into `data/.../alphafold/...` later, so `*_af.pdb` count may stay flat for a long time even while stage 16 is healthy.
- Keep `num_recycles=3` if prioritizing model quality over wall-clock time.

## LigQ_2 (binders enrichment)
- **Stage 24**, controlled by `TPW_LIGQ_USE_REMOTE`:
  - `0` (default): stage is skipped.
  - `1`: runs LigQ_2 remotely on a SLURM CPU node via `pipeline/ligq_remote.py`. **One SLURM job per genome** (LigQ_2 processes all proteins internally). Tested at 1m46s for 62 prots and 32min for 5572 prots.
- **Flow**: dump FASTA from DB → SCP to cranex → sbatch → poll → tar-pipe output back → `load_ligq_2_results` loads into `Binders`.
- **Evidence split**: PDB direct, PDB homolog, ChEMBL direct, ChEMBL homolog, ZINC. `is_direct=True` when LigQ_2's `uniprot_id` matches the protein's own `UnipSp`/`UnipTr` crossrefs.
- **UniProt prerequisite**: run `gbk2uniprot_map` before loading binders. If UniProt async idmapping returns HTTP 400, tpweb falls back to UniProtKB RefSeq xref search (`xref:RefSeq-NP_...`). If an empty `unips_mapping.csv` was cached, remove it and rerun.
- **Output filtering**: top 100 ChEMBL by pchembl, top 50 ZINC by tanimoto ≥ 0.5, all PDB-crystallized. Skips non-drug-like HET codes (amino acids, water, ions, buffers) by default.
- **Operations doc**: see `docs/BINDERS_LIGQ2.md` for manual cranex jobs, copying outputs back, reload commands, and direct/homolog verification.
- **Config** (env vars, all have defaults):
  - `TPW_LIGQ_USE_REMOTE=1` — activate remote mode
  - `TPW_LIGQ_DIR` — default `/home/agutson/work/LigQ_2`
  - `TPW_LIGQ_DATA_DIR` — default `/home/agutson/work/ligq_data`
  - `TPW_LIGQ_CONDA_PREFIX` — default `/home/shared/miniconda3.8`
  - `TPW_LIGQ_CONDA_ENV` — default `/home/agutson/work/conda_envs/ligq_2_local` (prefix env, not name)
  - `TPW_LIGQ_SLURM_PARTITION` — default `cpu`
  - `TPW_LIGQ_SLURM_TIME` — default `48:00:00`
  - `TPW_LIGQ_SLURM_MEM` — default `32G`
  - `TPW_LIGQ_SLURM_CPUS` — default `8`
  - `TPW_LIGQ_REMOTE_POLL_SEC` — default `60`
  - `TPW_LIGQ_REMOTE_WAIT_SEC` — default `172800` (48h)
  - `TPW_LIGQ_MAX_KNOWN` — default `100`
  - `TPW_LIGQ_MAX_ZINC` — default `50`
  - `TPW_LIGQ_MIN_TANIMOTO` — default `0.5`
- **Per-genome workspace**: `<folder_path>/ligq2/proteins.fasta`, `<folder_path>/ligq2/output/` (search_results subtree).
- **Remote workdir**: `${SSH_WORKDIR}/tpw_ligq/<safe_genome>_<timestamp>/`. Cleaning up after success is optional.

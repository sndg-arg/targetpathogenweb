# TargetPathogenWeb — Claude Context

## What this is
Django 4 web platform for genome-level protein exploration and bioinformatics target prioritization.
Thesis project at FCEN UBA. Stack: Django + PostgreSQL + Docker Compose.

## Key directories
```
pipeline/           # Pipeline orchestrator (run_pipeline_direct.py) and commands
tpweb/services/     # Business logic — pipeline_status.py, genome_uploads.py
tpweb/views/        # Thin views, delegate to services
tpweb/models/       # ORM models (GenomeUpload, PipelineRun, PipelineStageEvent, etc.)
tpwebconfig/        # Django settings, urls
static/css/         # Design system — tokens only, no hardcoded hex
```

## Pipeline architecture
- **Orchestrator**: `pipeline/run_pipeline_direct.py` — direct subprocess, no Parsl
- **Commands**: `pipeline/pipeline_commands.py` — one function per stage returning a bash command string
- **Activation**: `TPW_USE_DIRECT_PIPELINE=1` env var selects the new orchestrator
- **Legacy**: `pipeline/apps.py`, `pipeline/config.py`, `pipeline/run_pipeline.py` — old Parsl code, kept as fallback, do not modify
- **23 stages**, mostly linear — any failure raises immediately (no silent partial failures)
- **Remote stages**: stage 10 (InterProScan via `interproscan_remote.py`) and optionally stage 16 (ColabFold via `colabfold_remote.py`) run on SLURM cluster nodes over SSH
- **Parallelized stages**: stage 15 (AlphaFold downloads, 4 workers) and stage 17 (structure processing, 4 workers) use `ThreadPoolExecutor`. All other stages run sequentially.
- **Stage events** tracked in `PipelineStageEvent` model (submitted → completed/failed)
- **Status**: `tpweb/services/pipeline_status.py` — reads from `PipelineRun` as source of truth

## Pipeline stages overview
1. clear_folder → download/test/custom gbk → load_gbk
2. fasttarget → load_score (×3: human_offtarget, micro_offtarget, essenciality)
3. index_genome_db → index_genome_seq → interproscan (remote SSH) → load_interpro
4. gbk2uniprot_map → fetch_uniprot_annotations → alphafold loop → colabfold (local CPU or remote GPU) → structures chain → druggability → load_score
5. psort → load_score
6. get_binders → load_binders

## InterProScan
Runs remotely over SSH on the QB cluster. Config in `pipeline/settings.ini` (SSH vars).
Uses `-b output_prefix` flag (not `-o`/`-d` — they're mutually exclusive in v5.62).
conda env: `interproscan`. Key fix: `set -u` must come AFTER `conda activate`.
- Stage 10 can legitimately stay active for hours. First check SLURM state before assuming the pipeline is stuck.
- On cluster, the real source of truth is the remote SLURM job (`squeue` / `sacct` on `cluster.qb.fcen.uba.ar`), not the local Django banner.
- If `slurm-<jobid>.out` exists and shows `% completed`, InterProScan is healthy even if the UI still says stage 10.

## ColabFold
- **Two execution modes** for stage 16, controlled by `TPW_COLABFOLD_USE_REMOTE`:
  - `0` (default): runs locally on CPU inside `target2_nodo0_queue` via `colabfold_predict` management command. Extremely slow (~30–60 min per protein).
  - `1`: runs remotely on SLURM GPU nodes via `pipeline/colabfold_remote.py`. **One SLURM job per protein** (not batch), so one failure doesn't kill the rest.
- **Remote mode behavior**:
  - Proteins <= `TPW_COLABFOLD_MAX_SEQ_LENGTH` (default 800 aa) → GPU via SLURM
  - Proteins > limit → fallback to local ColabFold CPU (same quality, just slower)
  - If an individual GPU job fails → fallback to local CPU for that protein
  - Persists `job_id` and `remote_job_dir` in `PipelineRun`. On timeout/failure, does `scancel` to avoid orphan GPU jobs.
- **Remote GPU config** (env vars, all have defaults):
  - `TPW_COLABFOLD_USE_REMOTE=1` — activate remote mode
  - `TPW_COLABFOLD_CONDA_PREFIX` — default `/home/shared/miniconda3.8`
  - `TPW_COLABFOLD_CONDA_ENV` — default `colabfold`
  - `TPW_COLABFOLD_MAX_SEQ_LENGTH` — default `800` (safe for 8 GB VRAM GPUs like RTX 2080)
  - `TPW_COLABFOLD_PARTITION` — default `gpu`
  - `TPW_COLABFOLD_GRES` — default `gpu:1`
  - `TPW_COLABFOLD_TIME` — default `12:00:00`
  - `TPW_COLABFOLD_MEM` — default `16gb`
  - `TPW_COLABFOLD_NUM_RECYCLES` — default `3`
  - `TPW_COLABFOLD_NUM_MODELS` — default `1`
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

## PSORTb
Runs via Docker-in-Docker (`/var/run/docker.sock` mounted). Has fallback to `tpweb_psort_fallback` management command when Docker is unavailable.

## CSS rules (strict)
- Hex colors ONLY in `tpweb/templates/base/masterpage.html` (:root block)
- All other CSS: semantic tokens only (`--tp-color-*`, `--tp-ui-*`)
- One CSS file per page in `static/css/pages/`

## Deployment
- Local: `docker compose up --build -d`
- Cluster (Nodo0, QB FCEN UBA): `make build ENV=cluster && make up ENV=cluster`
- Cluster access: `ssh agutson@cluster.qb.fcen.uba.ar → sudo su glyco → ssh nodo0 → sudo su dockeradmin`
- Data lives in `/data/targetpathogen/` on cluster (RAID — never delete volumes)
- See `docs/CLUSTER_DEPLOY.md` for full deploy guide

## Debugging on cluster (nodo0)

### Container names
- `target2_nodo0_web` — Django web server (gunicorn)
- `target2_nodo0_queue` — Pipeline worker (processes genome queue)
- `target2_nodo0_db` — PostgreSQL
- `target2_nodo0_jbrowse` — JBrowse genome browser

### Running Django commands inside containers
Django needs conda activated. Always use this pattern:
```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py <command>"
```
Without conda: `ModuleNotFoundError: No module named 'django'`

### Checking pipeline run status
```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models import PipelineRun, PipelineStageEvent
run = PipelineRun.objects.order_by('-id').first()
print(f'Run {run.id} status={run.status} stage={run.current_stage}')
evts = PipelineStageEvent.objects.filter(pipeline_run=run).order_by('id')
for e in evts:
    print(f'  stage={e.stage_number} status={e.status} msg={e.message[:200] if e.message else str()}')\""
```
Note: the field is `pipeline_run` (not `run`), and `message` (not `error_message`).

### Viewing logs
```bash
# Queue worker (pipeline execution):
docker logs target2_nodo0_queue --tail=100

# Web server:
docker logs target2_nodo0_web --tail=100

# Via Makefile (follows live):
make logs ENV=cluster svc=queue
make logs ENV=cluster svc=web
```

### Common issues
- **Template not updating after change**: Django caches templates in production. Restart: `make restart ENV=cluster svc=web`
- **Queue container hangs on stop**: BLAST ignores SIGTERM. Use `docker kill target2_nodo0_queue` then `make up ENV=cluster`
- **"Genome X has already been processed"**: Delete the Biodatabase objects in Django shell, not just uploads/pipeline runs
- **Static files missing (404)**: Run `collectstatic` inside web container, or rebuild image if file wasn't in git
- **SSH "Bad owner or permissions"**: The mounted `.ssh` dir has wrong owner for paramiko. `start_queue.sh` handles this by copying to `/tmp/fakehome/.ssh` and setting `HOME=/tmp/fakehome`
- **SSH "Authentication failed"**: Check that `id_ed25519_agutson_cluster` key exists in `/home/dockeradmin/.ssh/` on nodo0 and is authorized in `~agutson/.ssh/authorized_keys` on cranex
- **Global pipeline banner says stage N, but Genomes page says "No genomes yet"**: expected when the `PipelineRun` is active but no `Biodatabase` has been loaded yet. The banner reads `PipelineRun`; the Genomes page lists `Biodatabase` rows only.
- **`run_log_path` / `launch_pid` debugging**: those values are container-local. Tail the log and inspect the PID inside `web` / `queue`, not on the host.

### Checking remote InterProScan job (SLURM)
```bash
# Job status (replace JOB_ID):
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "sacct -j JOB_ID --format=JobID,State,Elapsed,ExitCode -P"

# Job output/progress:
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "tail -20 /home/agutson/tpw_interpro/*/slurm-JOB_ID.out"
```
The SLURM job ID appears in the stage event message (e.g. "Submitted remote InterProScan job 194464").

### Checking ColabFold progress

**Remote GPU mode** (`TPW_COLABFOLD_USE_REMOTE=1`):
```bash
# Find the SLURM job ID from pipeline events:
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models import PipelineStageEvent
evt = PipelineStageEvent.objects.filter(app_name='colabfold_remote').order_by('-id').first()
print(evt.message, evt.payload)\""

# Check SLURM job status (replace JOB_ID):
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "sacct -j JOB_ID --format=JobID,State,Elapsed,ExitCode -P"

# Follow remote ColabFold log (replace JOB_DIR from payload):
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "tail -30 JOB_DIR/slurm-JOB_ID.out"

# Count PDBs produced so far on the remote node:
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "ls JOB_DIR/output/*rank_001*.pdb 2>/dev/null | wc -l"
```

**Local CPU mode** (`TPW_COLABFOLD_USE_REMOTE=0`):
```bash
# Discover the temporary ColabFold directory:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "find /tmp -maxdepth 2 -type d -name 'colabfold_*' -print"

# Follow the ColabFold log:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "tail -f /tmp/colabfold_*/output/log.txt"

# Show the latest query only:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "grep 'Query ' /tmp/colabfold_*/output/log.txt | tail -1"
```

**Both modes** — count final PDBs in workspace (replace ACC):
```bash
find /data/targetpathogen/data -path '*ACC/alphafold/*/*_af.pdb' | wc -l
```

### Resetting a genome for re-processing
```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models import GenomeUpload, PipelineRun
from tpweb.services.genome_uploads import delete_genome_workspace
u = GenomeUpload.objects.filter(owner__username='public').order_by('-created_at', '-id').first()
acc = u.internal_accession
print(f'Deleting upload id={u.id} accession={acc} status={u.status}')
delete_genome_workspace(acc, owner=u.owner)
PipelineRun.objects.filter(internal_accession=acc).delete()
from bioseq.models.Biodatabase import Biodatabase
Biodatabase.objects.filter(name__contains=u.accession).delete()
print(acc)\""

# Then remove only the matching on-disk paths (replace ACC with the value printed above):
ACC='public__ACCESSION_HERE'
MID=$(ACC="$ACC" python3 - <<'PY'
import math, os
acc = os.environ['ACC']
print(acc[math.floor(len(acc)/2 - 1):math.floor(len(acc)/2 + 2)])
PY
)
sudo rm -rf -- "/data/targetpathogen/data/${MID}/${ACC}"
sudo rm -rf -- "/data/targetpathogen/fasttarget_organism/${ACC}"
```

## Importing external analysis results (Gates-Targets pipeline)

Use `import_external_results` to load pre-computed scores + structures into TPW without re-running the full pipeline.

### 1. Load the genome first
Upload the `.gbk.gz` via the web UI (Genomes → Upload), let it run through stage 3 (load_gbk), then stop the pipeline.

### 2. Transfer files to the server

**glyco cannot write to `/data/targetpathogen/data/` directly** — use `/tmp/` on nodo0 as a staging area instead.

From cranex (after copying files there with scp from your Mac):
```bash
# TSV only (small — copy directly to the data volume via docker):
docker exec target2_nodo0_web bash -c "cat > /tmp/results_table.tsv" < results_table.tsv

# Large files (structures tar ~850MB) — scp to /tmp/ on nodo0, then access from container:
scp /home/agutson/ATCC43816_structures_only.tar.gz glyco@nodo0:/tmp/ATCC43816_structures_only.tar.gz
```

The container can read `/tmp/` on the host because nodo0's `/tmp/` is accessible from inside the container at the same path.

### 3. Extract the structures tar inside the container
```bash
docker exec target2_nodo0_queue bash -c "tar -xzf /tmp/ATCC43816_structures_only.tar.gz -C /tmp/"

# Verify extraction (check one PDB):
docker exec target2_nodo0_queue find /tmp -name "*.pdb" -maxdepth 6 | head -3
```

### 4. Run the import command
```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py import_external_results public__KpATCC43816 \
  --results-tsv /tmp/results_table.tsv \
  --structures-dir /tmp/KpATCC43816/structures \
  --datadir /app/targetpathogenweb/data \
  --overwrite"
```

Replace `public__KpATCC43816` with the actual internal accession (shown in the Genomes page URL or upload history). Adjust `--structures-dir` to match the actual extraction path.

### 5. Run remaining pipeline stages manually (optional)
After importing, stages that haven't run yet (UniProt mapping, binders, InterProScan) can still be kicked off via the web UI or management commands.

### Gates TSV → TPW column mapping
| Gates column | TPW ScoreParam |
|---|---|
| `human_offtarget` | `human_offtarget` |
| `druggability_score` | `Druggability` |
| `psortb_localization` | `Localization` |
| `gut_microbiome_offtarget_norm` | `gut_microbiome_offtarget_norm` |
| `gut_microbiome_offtarget_counts` | `gut_microbiome_offtarget_counts` |
| `colabfold_plddt` | `colabfold_plddt` |
| `core_roary` | `core_roary` |
| `core_corecruncher` | `core_corecruncher` |

## Running tests
```bash
# Inside container (preferred):
docker compose exec web bash -c "DJANGO_SETTINGS_MODULE=tpwebconfig.settings python -m django test tpweb.tests.PipelineStatusTests"
# Note: custom 'test' management command shadows Django's built-in — use python -m django test
```

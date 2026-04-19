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
- **23 stages**, fully linear — any failure raises immediately (no silent partial failures)
- **Stage events** tracked in `PipelineStageEvent` model (submitted → completed/failed)
- **Status**: `tpweb/services/pipeline_status.py` — reads from `PipelineRun` as source of truth

## Pipeline stages overview
1. clear_folder → download/test/custom gbk → load_gbk
2. fasttarget → load_score (×3: human_offtarget, micro_offtarget, essenciality)
3. index_genome_db → index_genome_seq → interproscan (remote SSH) → load_interpro
4. gbk2uniprot_map → fetch_uniprot_annotations → alphafold loop → colabfold → structures chain → druggability → load_score
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
- Stage 16 runs inside `target2_nodo0_queue`, not on SLURM.
- `run_pipeline_direct.py` executes `colabfold_predict` with `capture_output=True`, so live ColabFold progress does NOT appear in `docker logs target2_nodo0_queue`.
- Real progress is in `/tmp/colabfold_*/output/log.txt` inside the queue container:
  - `Query N/total`
  - `recycle=...`
  - `rank_001...`
- ColabFold output is written to a temporary directory first and copied into `data/.../alphafold/...` later, so the final `*_af.pdb` count may stay flat for a long time even while stage 16 is healthy.
- CPU-only runs are extremely slow. With `TPW_COLABFOLD_NUM_RECYCLES=3`, long proteins can take >1 hour each. Keep `num_recycles=3` if prioritizing model quality over wall-clock time.

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

### Checking live ColabFold progress
```bash
# Discover the temporary ColabFold directory:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "find /tmp -maxdepth 2 -type d -name 'colabfold_*' -print"

# Follow the ColabFold log:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "tail -f /tmp/colabfold_*/output/log.txt"

# Show the latest query only:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "grep 'Query ' /tmp/colabfold_*/output/log.txt | tail -1"

# Count final PDBs copied into the workspace:
find /data/targetpathogen/data -path '*public__NZ_AP023069.1/alphafold/*/*_af.pdb' | wc -l
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
print(acc)\""

# Then remove only the matching on-disk paths (replace ACC if needed):
ACC='public__NZ_AP023069.1'
MID=$(ACC="$ACC" python3 - <<'PY'
import math, os
acc = os.environ['ACC']
print(acc[math.floor(len(acc)/2 - 1):math.floor(len(acc)/2 + 2)])
PY
)
sudo rm -rf -- "/data/targetpathogen/data/${MID}/${ACC}"
sudo rm -rf -- "/data/targetpathogen/fasttarget_organism/${ACC}"
```

## Running tests
```bash
# Inside container (preferred):
docker compose exec web bash -c "DJANGO_SETTINGS_MODULE=tpwebconfig.settings python -m django test tpweb.tests.PipelineStatusTests"
# Note: custom 'test' management command shadows Django's built-in — use python -m django test
```

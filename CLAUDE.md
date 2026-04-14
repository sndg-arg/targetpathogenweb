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

## Running tests
```bash
# Inside container (preferred):
docker compose exec web bash -c "DJANGO_SETTINGS_MODULE=tpwebconfig.settings python -m django test tpweb.tests.PipelineStatusTests"
# Note: custom 'test' management command shadows Django's built-in — use python -m django test
```

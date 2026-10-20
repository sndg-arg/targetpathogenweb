# Target Pathogen Web — Claude Context

## What this is
Django 4 web platform for genome-level protein exploration and bioinformatics target prioritization.
Thesis project at FCEN UBA. Stack: Django + PostgreSQL + Docker Compose.

## Key directories
```
pipeline/           # Pipeline orchestrator (run_pipeline_direct.py) and commands
tpweb/services/     # Business logic — pipeline_status.py, genome_uploads.py
tpweb/views/        # Thin views, delegate to services
tpweb/models/       # ORM models (GenomeUpload, PipelineRun, PipelineStageEvent, etc.)
human_target/       # Separate Django app: Target Human (see "Human Targets" below)
tpwebconfig/        # Django settings, urls
static/css/         # Design system — tokens only, no hardcoded hex
```

## Context docs (read only the one the task needs)
Detail lives in `docs/context/` so it isn't loaded every session. Older code comments that say
"see CLAUDE.md's X section" mean the section of the same name in these files.
- `PIPELINE.md` — Pipeline architecture (orchestrator `pipeline/run_pipeline_direct.py`, 23 stages,
  stage events, orphaned-run reconciliation, `cancel_pipeline_run`), Pipeline stages overview, PSORTb.
- `REMOTE_STAGES.md` — FastTarget (stage 4), InterProScan (stage 10), ColabFold (stage 16), LigQ_2
  (stage 24): SLURM flow and every `TPW_*` env var with its default.
- `HUMAN_TARGETS.md` — Human Targets (`human_target/` app): storage, pilot ingest, full-proteome bulk
  commands, cross-app template gotcha.
- `FEATURES.md` — Cross-strain identical-sequence links, Metabolic pathway integration, Access
  control (login wall vs. IP blocking).
- `CLUSTER_OPS.md` — Debugging on cluster (container names, status/log/SLURM commands, genome
  reset), Moving large files neocranex → nodo0, Importing external analysis results (Gates).

## CSS rules (strict)
- Hex colors ONLY in `tpweb/templates/base/masterpage.html` (:root block)
- All other CSS: semantic tokens only (`--tp-color-*`, `--tp-ui-*`)
- One CSS file per page in `static/css/pages/`

## Deployment
- Local: `docker compose up --build -d`
- Production = Nodo0 on the QB FCEN UBA cluster, live at https://target2.infra.cluster.qb.fcen.uba.ar/.
  A push to GitHub does NOT deploy; the user pulls + rebuilds on Nodo0 by hand.
- Cluster access: `ssh agutson@cluster.qb.fcen.uba.ar → su glyco → ssh nodo0 → sudo su dockeradmin → cd ~/targetpathogenweb`
- Cluster update (live branch is `misc-fixes`):
  `git pull origin misc-fixes && make build ENV=cluster && make up ENV=cluster && make migrate ENV=cluster`
- Data lives in `/data/targetpathogen/` on cluster (RAID — never delete volumes)
- Nodo0 is a shared orchestration node, not a bioinformatics compute node. Do
  not run full-proteome BLAST/HMMER, InterProScan, LigQ_2, AlphaFold/ColabFold,
  FPocket, or P2Rank directly on Nodo0; use SLURM-backed remote stages.
- Use cached service-scoped cluster builds (`make build ENV=cluster svc=web`;
  `make up ENV=cluster svc=web`). Avoid `--no-cache` unless fixing a concrete
  image-cache problem.
- See `docs/CLUSTER_DEPLOY.md` for the full Nodo0 operating policy, SLURM
  monitoring commands, and large-file transfer workflow.

## Running tests
`tpweb/tests.py` was split into a package: `tpweb/tests/test_services.py` (services,
management-command helpers, LLM adapters), `tpweb/tests/test_views_smoke.py` (route/view
smoke tests), more `test_*.py` files can be added freely — Django discovers them by app
label. `pipeline/` isn't a Django app (no `__init__.py`, invoked as a standalone script), so
its tests live separately under `pipeline/tests/` and run as a plain `unittest` suite.

```bash
# One command, runs both suites (tpweb app tests + pipeline/tests):
make test
# equivalent to: docker compose exec web python scripts/run_tests.py

# A single test class, inside container:
docker compose exec web bash -c "DJANGO_SETTINGS_MODULE=tpwebconfig.settings python -m django test tpweb.tests.test_services.PipelineStatusTests"
# Note: custom 'test' management command shadows Django's built-in — use python -m django test

# Lint (whole repo, same as CI):
make lint
make format        # auto-fix

# Coverage report:
make coverage
```

### Enforcement
- **Local git hooks** (`make precommit-install`, run once after cloning): on every `commit`,
  ruff + basic hygiene checks run (fast, no DB needed). On every `push`, the full test suite
  runs (`scripts/run_tests.py`) — this is what actually needs Postgres, so it only runs at
  push time, not on every small commit. Config lives in `.pre-commit-config.yaml`.
- **CI** (`.github/workflows/qa.yml`): runs on every PR and on push to `main`/`master` —
  Django system check, full test suite with coverage, and `ruff check .` / `ruff format
  --check .` across the whole repo (not a hardcoded file list).
- **Branch protection**: `main` requires the `QA / checks` status check to pass before a PR
  can be merged.

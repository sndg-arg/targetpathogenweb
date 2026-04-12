# Target Pathogen Web

Web platform for genome-level protein exploration, structural evidence analysis, and bioinformatics target prioritization.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 4, Python 3.10 |
| Database | PostgreSQL 14 |
| Pipeline | subprocess orchestrator + bioinformatics tools (InterProScan, AlphaFold, FPocket, P2Rank, PSORTb) |
| Frontend | Django templates, modular CSS (design tokens), vanilla JS |
| Auth | django-allauth (username/email login, admin-only registration) |
| Runtime | Docker Compose (4 services: web, db, queue, jbrowse) |

## Architecture

```
tpweb/
├── views/           # Request handling — thin, delegates to services
├── services/        # Business logic — reusable, testable
├── models/          # Django ORM models (TPUser, GenomeUpload, PDB, Binders, etc.)
├── templates/       # Django templates (extends base/masterpage.html)
├── management/      # Custom manage.py commands (pipeline, data imports)
├── forms/           # Django forms (upload, user)
├── adapters/        # django-allauth adapters
├── middleware/       # Request timing observability
└── io/              # File parsers (FPocket, PDB)

static/
├── css/components/  # Shared UI system (ui-system.css)
├── css/pages/       # Page-specific styles (one file per page)
├── js/pages/        # Page-specific JS (protein-detail.js, etc.)
└── bundle.js        # Webpack bundle (feature-viewer, MSA, 3D libs)

pipeline/             # Pipeline orchestrator and commands
tpwebconfig/         # Django project settings, urls, wsgi
```

### Key conventions

- **Views** parse inputs and return responses. No business logic.
- **Services** hold domain logic. Views call services.
- **CSS** uses semantic design tokens (`--tp-color-*`). No hardcoded hex outside `masterpage.html`.
- **Templates** extend `base/masterpage.html`. Page styles load via `{% block head %}`.
- **Dark mode** is fully supported via `.tp-dark` class and token overrides.

## Quick Start

```bash
# 1. Local env
cp .env.local.example .env
docker network create web 2>/dev/null || true

# 2. Build + start
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up --build -d

# 3. Verify
docker compose ps
curl -s http://localhost:8085/health/live
```

Open: http://localhost:8085

Minimal deploy files:

- `docker-compose.yml` for the base stack
- `docker-compose.cluster.yml` only for cluster overrides
- `.env.local.example` for local
- `.env.cluster.example` for cluster

FastTarget databases are mounted from the host via `TPW_FASTTARGET_DB_DIR` instead of being baked into the app image. Runtime outputs stay in `TPW_FASTTARGET_RUNTIME_DIR` and `TPW_FASTTARGET_LOG_DIR`.

Local runs also mount `${HOME}/.ssh` into `web` and `queue`, because remote pipeline stages submit work to the QB cluster over SSH.

### First admin user

```bash
docker compose exec web python manage.py createsuperuser
```

Regular users are created from Django admin (`/admin/` → Users → Add user). Public registration is disabled.

## Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| web | `target2_nodo0` | 8085→8000 | Django app |
| db | `db_target2_nodo0` | 5432 | PostgreSQL |
| queue | `target2_queue_nodo0` | — | Genome pipeline worker |
| jbrowse | `target2_jbrowse_nodo0` | 3000 | Genome browser |

## URL Map

| URL | View | Description |
|-----|------|-------------|
| `/` | Home | Landing page |
| `/genomes/` | GenomesList | All accessible genomes |
| `/genome/<accession>/` | Assembly | Genome overview |
| `/genome/<accession>/proteins` | ProteinList | Filterable protein table |
| `/genome/<accession>/explore/<ec\|go>` | AnnotationExplorer | Sunburst (Krona-style) annotation chart |
| `/genome/<accession>/parameters` | ParameterForm | Scoring criteria editor |
| `/genome/<accession>/formula` | FormulaForm | Scoring formula builder |
| `/protein/<id>` | ProteinView | Protein detail (structure, annotations, binders) |
| `/structure/<id>` | StructureView | Full-screen 3D structure + pockets |
| `/upload/` | GenomeUpload | Upload genome, trigger pipeline |
| `/form/` | BLAST | Sequence search |
| `/accounts/login/` | allauth | Login |
| `/admin/` | Django admin | User management, data admin |

### URL design

URLs use clean accessions (e.g. `/genome/NZ_AP023069.1/proteins`), not internal workspace names. The resolver (`genome_workspace.resolve_genome_from_slug`) maps accessions back to internal names transparently.

## Pipeline

The genome processing pipeline runs 23 stages via a direct subprocess orchestrator:

1. **Genome acquisition** — download from NCBI, use test genome, or upload `.gbk.gz`
2. **Import** — load GenBank into database
3. **FastTarget scoring** — human off-target, microbiome off-target, essentiality
4. **Indexing** — DB and sequence indexes
5. **Functional annotation** — InterProScan → load annotations
6. **UniProt mapping** — protein-to-UniProt ID mapping
7. **Structure prediction** — AlphaFold models + FPocket/P2Rank pocket analysis
8. **Druggability & localization** — druggability score, PSORTb
9. **Binders** — extract and load binder candidates

### Run pipeline manually

```bash
docker compose exec -it web bash
source /opt/conda/etc/profile.d/conda.sh && conda activate tpv2
cd /app/targetpathogenweb/pipeline && source exports.sh
python run_pipeline.py --test                    # test genome
python run_pipeline.py --gram n NC_002516.2      # NCBI accession
python run_pipeline.py --gram n --custom file.gbk.gz  # custom file
```

### Monitor

```bash
curl -s http://localhost:8085/health/pipeline
docker compose exec web tail -f /tmp/tpw_pipeline_test.log
```

### Recover stuck pipeline

```bash
docker compose exec web bash -lc '
  pids=$(ps -eo pid,args | grep -E "run_pipeline|process_worker_pool|fasttarget" | grep -v grep | awk "{print \$1}")
  [ -n "$pids" ] && echo "$pids" | xargs kill -TERM
'
```

## Scoring System

Proteins are scored via configurable formulas. Each formula combines weighted evidence parameters:

- **Score parameters**: druggability, essentiality, human off-target, microbiome off-target, PSORTb localization
- **Formulas**: user-defined weighted combinations of parameters
- **Filters**: narrow protein list by parameter values, structure source, EC/GO annotations

The protein list supports search, pagination, column selection, CSV/XLSX export, and the criteria drawer for interactive filtering.

## Annotation Explorer

The EC/GO annotation explorer renders a Plotly sunburst chart. For EC numbers:

- Hierarchy: class → subclass → sub-subclass → enzyme (4 levels)
- Labels come from `tpweb/data/ec_hierarchy_labels.json` (authoritative source: ExPASy)
- Rebuild labels: `python manage.py fetch_ec_nomenclature`

## Frontend Build (bundle.js)

Only needed when changing JS dependencies (feature-viewer, MSA viewer, etc.):

```bash
cd js
docker build -t tpweb-webpack .
docker run --rm -w "$PWD" -v "$PWD:$PWD" tpweb-webpack bash -lc 'npm install && npm run build'
cp bundle.js ../static/bundle.js
```

## Design System

All colors use CSS custom properties defined in `masterpage.html`:

| Token family | Usage |
|-------------|-------|
| `--tp-color-text-*` | Text hierarchy (primary, secondary, muted, soft) |
| `--tp-color-brand-*` | Brand accent (050–900) |
| `--tp-color-surface*` | Backgrounds (surface, soft, muted, panel) |
| `--tp-color-border*` | Borders (soft, default, strong) |
| `--tp-color-success-*` | Positive states (green) |
| `--tp-color-warning-*` | Caution states (amber) |
| `--tp-color-danger-*` | Error states (red) |
| `--tp-color-info-*` | Informational states (blue) |

Dark mode overrides all tokens via `:root.tp-dark`. Theme toggle is in the sidebar footer.

### CSS file convention

- `static/css/components/ui-system.css` — shared tokens, table system, panels
- `static/css/pages/<page>.css` — one file per page, loaded in `{% block head %}`
- Cache busting: `?v=YYYYMMDD-N` suffix on CSS links in templates

## Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health/live` | Process alive |
| `GET /health/ready` | DB + dependencies ready (200/503) |
| `GET /health/pipeline` | Pipeline status JSON |

## Development

```bash
make lint      # ruff check
make format    # ruff format
make test      # run tests (inside container recommended)
make qa        # lint + tests
```

Tests run best inside the container (DB host is `db`):

```bash
docker compose exec web make qa
```

## Cluster Deployment

See [docs/CLUSTER_DEPLOY.md](docs/CLUSTER_DEPLOY.md). Minimal flow:

```bash
cp .env.cluster.example .env
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up --build -d
docker compose exec web python manage.py createsuperuser
```

## License

See [LICENSE](./LICENSE).

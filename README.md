# TargetPathogenWeb

Web application for genome/protein exploration and bioinformatics target prioritization.

## 1. Project Stack

- Backend: Django
- Database: PostgreSQL
- Pipeline: Parsl + bioinformatics tools
- Frontend: Django templates + modular CSS + JS bundle
- Runtime: Docker Compose (recommended)

## 2. Quick Start (Docker)

Prerequisites:

- Docker + Docker Compose plugin
- `make` (optional but recommended)

From repository root:

```bash
docker network create web 2>/dev/null || true
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --pull never
docker compose ps
```

Open: `http://localhost:8085`

## 3. Health Checks

```bash
curl -s http://localhost:8085/health/live
curl -s http://localhost:8085/health/ready
curl -s http://localhost:8085/health/pipeline
```

Meaning:

- `/health/live`: app process is alive
- `/health/ready`: app dependencies (including DB) are ready
- `/health/pipeline`: current pipeline status details

## 4. Development Commands

| Command | What it does | When to use |
| --- | --- | --- |
| `make format` | Runs `ruff format` | Before committing Python changes |
| `make lint` | Runs `ruff check` | Fast static checks during development |
| `make test` | Runs `scripts/run_tests.py` (`tpweb.tests`) | Validate behavior changes |
| `make qa` | Runs lint + tests | Final local verification |
| `make precommit-install` | Installs git hooks | Once per machine |
| `make precommit-run` | Runs all configured hooks | Before opening a PR |

## 5. Recommended Test Execution

Because project settings use DB host `db`, tests are most stable inside the container:

```bash
docker compose up -d db web
docker compose exec web make test
docker compose exec web make qa
```

## 6. Pipeline Quick Run

```bash
docker compose exec -it web bash
source /opt/conda/etc/profile.d/conda.sh
conda activate tpv2
cd /app/targetpathogenweb/parsl
source exports.sh
python run_pipeline.py --test
```

## 7. Documentation Map

Start here: [docs/README.md](./docs/README.md)

- [docs/OPERATIONS.md](./docs/OPERATIONS.md)
- [docs/ENGINEERING.md](./docs/ENGINEERING.md)
- [docs/FRONTEND_UI.md](./docs/FRONTEND_UI.md)

## 8. Main Structure

- `tpweb/views/*`: request handling and response composition
- `tpweb/services/*`: reusable business logic
- `tpweb/templates/*`: Django templates
- `static/css/components/*`: shared UI styles
- `static/css/pages/*`: page-specific styles
- `parsl/*`: pipeline implementation
- `scripts/run_tests.py`: test runner
- `Makefile`: local command shortcuts

## 9. Quick Troubleshooting

- Compose fails due to missing `web` network:
  - run `docker network create web`
- CSS/JS changes not visible:
  - hard refresh browser (`Cmd+Shift+R`)
- Host test run fails due to DB host mismatch:
  - run tests inside `web` container

## 10. License

See [LICENSE](./LICENSE).

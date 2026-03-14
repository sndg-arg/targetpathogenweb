# Operations Guide

This document centralizes runtime and operational procedures for TPWeb:

- Local startup and shutdown
- Health and observability endpoints
- Pipeline execution and monitoring
- Recovery actions for stuck runs

## 1. Prerequisites

- Docker + Docker Compose plugin installed
- Commands run from repository root (`targetpathogenweb`)

## 2. Start Services

### Local profile

```bash
cp .env.local.example .env
docker network create web 2>/dev/null || true
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --pull never
docker compose -f docker-compose.yml -f docker-compose.local.yml ps
```

### Cluster profile

```bash
cp .env.cluster.example .env
# Edit .env to match cluster paths, SSH host, and resource limits if needed.
docker network create web 2>/dev/null || true
DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose -f docker-compose.yml -f docker-compose.cluster.yml up -d --pull never
docker compose -f docker-compose.yml -f docker-compose.cluster.yml ps
```

What each command does:

- `docker network create web ...`: ensures external Docker network exists
- `docker compose ... up ...`: starts `db`, `web`, and `queue` in background
- `docker compose ... ps`: verifies service status

App URL: `http://localhost:8085`

### Compose file roles

- [docker-compose.yml](../docker-compose.yml): shared base configuration
- [docker-compose.local.yml](../docker-compose.local.yml): local workstation overrides
- [docker-compose.cluster.yml](../docker-compose.cluster.yml): cluster host overrides
- [docker-compose.override.yml](../docker-compose.override.yml): backward-compatible local shortcut for plain `docker compose up`

## 3. Health and Observability

### Health endpoints

```bash
curl -s http://localhost:8085/health/live
curl -s http://localhost:8085/health/ready
curl -s http://localhost:8085/health/pipeline
```

Meaning:

- `GET /health/live`: process liveness
- `GET /health/ready`: readiness (DB + dependencies), `200` healthy / `503` degraded
- `GET /health/pipeline`: current pipeline stage/task/run metadata

### Request timing

- Middleware: `tpweb.middleware.observability.RequestTimingMiddleware`
- Response header: `X-Request-Duration-Ms`
- Logs include method, path, status, duration

## 4. Pipeline Execution (Parsl)

### Enter runtime context

```bash
docker compose exec -it web bash
source /opt/conda/etc/profile.d/conda.sh
conda activate tpv2
cd /app/targetpathogenweb/parsl
source exports.sh
```

Why this context:

- Ensures expected Conda environment and binaries
- Uses runtime container paths

### Profiles

`exports.sh` supports:

- cluster-safe (default)
- local profile (`export TPW_PROFILE=local`)

The selected profile comes from Compose:

- local: `docker-compose.local.yml` sets `TPW_PROFILE=local`
- cluster: `docker-compose.cluster.yml` sets `TPW_PROFILE=cluster`

### Common runs

Test genome:

```bash
python run_pipeline.py --test
```

NCBI accession example:

```bash
python run_pipeline.py --gram n NC_002516.2
```

Custom input example:

```bash
python run_pipeline.py --gram n --custom NC_002516.2.gbk.gz
```

### Pipeline stage table (21 stages)

These stage numbers match what the app reports in `GET /health/pipeline`.

| Stage | Parsl app(s) | What it does | Main output/effect |
| --- | --- | --- | --- |
| 1 | `clear_folder` | Removes previous run folder for that genome | Clean working directory |
| 2 | `test_gbk` / `download_gbk` / `custom_gbk` | Obtains genome input (`--test`, NCBI download, or custom file) | Genome GBK available for load |
| 3 | `load_gbk` | Imports GBK into Django/DB | Genome records loaded |
| 4 | `fasttarget` | Runs FastTarget scoring pipeline | Raw scoring files generated |
| 5 | `load_score` (`human_offtarget`) | Loads human off-target score | Score values persisted |
| 6 | `load_score` (`micro_offtarget`) | Loads microbiome off-target score | Score values persisted |
| 7 | `load_score` (`essenciality`) | Loads essentiality score | Score values persisted |
| 8 | `index_genome_db` | Builds DB-oriented indexes | Indexed metadata for queries |
| 9 | `index_genome_seq` | Builds sequence/annotation indexes | Indexed sequence artifacts |
| 10 | `interproscan` | Runs InterProScan for functional annotations | InterPro TSV generated |
| 11 | `load_interpro` | Loads InterPro annotations into DB | Annotation records persisted |
| 12 | `gbk2uniprot_map` | Maps genome proteins to UniProt IDs | Mapping files generated |
| 13 | `get_unipslst` | Reads/collects mapped UniProt list | UniProt list in memory for next step |
| 14 | `alphafold_unips` | Generates AlphaFold models for mapped proteins | Protein structure files |
| 15 | `strucutures_af` + (`load_af_model`, `fpocket2json`, `load_pocket`, `p2rank2json`, `load_p2pocket`) | Loads structures and pocket predictions | Structure + pocket data persisted |
| 16 | `druggability_2_csv` | Converts druggability results to ingest format | Druggability TSV/CSV ready |
| 17 | `load_score` (`druggability`) | Loads druggability score | Score values persisted |
| 18 | `psort` | Runs subcellular localization prediction | PSORT output generated |
| 19 | `load_score` (`psort`) | Loads PSORT score | Score values persisted |
| 20 | `get_binders` | Extracts binder candidates | Binder candidate dataset |
| 21 | `load_binders` | Loads binder candidates into DB | Binder records persisted |

### High-level phase map

1. Genome acquisition and import
2. FastTarget scoring and score loads
3. Genome indexing and functional annotation
4. Structure and pocket processing
5. Druggability and localization scoring
6. Binder extraction and load

## 5. Local Pipeline Test Flow

### Reset previous runtime artifacts (keeps DB biological data)

```bash
docker compose exec -T web bash -lc '
  rm -rf /app/targetpathogenweb/parsl/runinfo/* \
         /app/targetpathogenweb/runinfo/* \
         /tmp/tpw_pipeline_test.log \
         /tmp/tpw_pipeline_test.pid
  mkdir -p /app/targetpathogenweb/parsl/runinfo /app/targetpathogenweb/runinfo
'
```

### Launch test run in background

```bash
docker compose exec -T web bash -lc '
  cd /app/targetpathogenweb/parsl
  source /opt/conda/etc/profile.d/conda.sh
  conda activate tpv2
  source exports.sh
  export TPW_PROFILE=local
  export PYTHONPATH=/app/targetpathogenweb/parsl:/app/targetpathogenweb:$PYTHONPATH
  nohup python run_pipeline.py --test > /tmp/tpw_pipeline_test.log 2>&1 &
  echo $! > /tmp/tpw_pipeline_test.pid
  echo "started pid $(cat /tmp/tpw_pipeline_test.pid)"
'
```

### Monitor progress

```bash
curl -s http://localhost:8085/health/pipeline
docker compose exec -T web bash -lc 'tail -f /tmp/tpw_pipeline_test.log'
docker compose exec -T web bash -lc 'ps -eo pid,args | grep -E "run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep'
```

Optional polling:

```bash
watch -n 5 'curl -s http://localhost:8085/health/pipeline'
```

## 6. Recover Stuck Pipeline

```bash
docker compose exec -T web bash -lc '
  pids=$(ps -eo pid,args | grep -E "python .*run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep | awk "{print \$1}" || true)
  [ -n "$pids" ] && echo "$pids" | xargs -r kill -TERM
  sleep 2
  pids=$(ps -eo pid,args | grep -E "python .*run_pipeline.py|process_worker_pool.py|fasttarget.py" | grep -v grep | awk "{print \$1}" || true)
  [ -n "$pids" ] && echo "$pids" | xargs -r kill -KILL
'
```

Use only when a run is clearly hung.

## 7. Stop Services

Pause containers and resume later:

```bash
docker compose stop
```

Restart stopped containers:

```bash
docker compose start
```

Remove compose resources:

```bash
docker compose down
```

Remove compose resources and volumes (destructive):

```bash
docker compose down -v
```

## 8. Safety Rules

- Keep credentials and personal paths out of version control (`parsl/settings.ini`)
- Use `.env.local.example` / `.env.cluster.example` as the source for machine-specific `.env`
- Keep `docker-compose.yml` environment-neutral; put machine-specific mounts in `docker-compose.local.yml` or `docker-compose.cluster.yml`
- Prefer tests/QA inside `web` container for environment consistency
- Keep docs, UI, and pipeline logic changes in separate commits when possible

## 9. Related

- Root setup and development commands: [../README.md](../README.md)
- Engineering standards: [./ENGINEERING.md](./ENGINEERING.md)
- Frontend and UI standards: [./FRONTEND_UI.md](./FRONTEND_UI.md)

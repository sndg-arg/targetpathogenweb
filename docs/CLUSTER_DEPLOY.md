# Cluster Deployment Guide — Nodo0 (QB FCEN UBA)

## Access

```bash
ssh agutson@cluster.qb.fcen.uba.ar
sudo su glyco
ssh nodo0
sudo su dockeradmin
```

Files live in `/home/dockeradmin/targetpathogenweb/`.
Persistent data lives in `/data/targetpathogen/` (RAID, never delete).

---

## Nodo0 Operating Rules

Nodo0 is a shared orchestration node. Treat it as the place where Docker,
Traefik, PostgreSQL, small Django management commands, and file staging happen.
It is not a bioinformatics compute node.

Allowed on Nodo0:

- `git pull`, `git status`, and normal repo inspection
- `make build ENV=cluster svc=<service>` and `make up ENV=cluster svc=<service>`
- `docker compose exec` into `web` or `queue` for lightweight Django commands
- database audits, row counts, coverage summaries, and metadata checks
- loading already-computed TSV/JSON/PDB metadata into the database
- copying, moving, listing, and extracting files in `/data/targetpathogen/data`
- monitoring local logs and remote SLURM jobs

Do not run on Nodo0:

- BLAST/HMMER searches over full proteomes
- InterProScan
- LigQ_2
- AlphaFold or ColabFold
- FPocket or P2Rank over full proteomes
- large custom Python/R scripts that iterate all structures/sequences with
  heavy CPU, memory, or disk churn
- ad hoc `docker compose build --no-cache` unless debugging a specific image
  corruption problem
- `docker compose down -v`, `rm -rf /data/targetpathogen`, or any command that
  deletes persistent volumes

Use remote SLURM-backed pipeline stages for heavy work. If a command is expected
to spend minutes to hours doing sequence search, structural prediction, pocket
prediction, or LigQ analysis, it belongs on a compute node via the TPW remote
wrappers, not directly on Nodo0.

Good default deployment pattern:

```bash
cd /home/dockeradmin/targetpathogenweb
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=web
make up ENV=cluster svc=web
```

For queue-only code changes:

```bash
cd /home/dockeradmin/targetpathogenweb
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=queue
make up ENV=cluster svc=queue
```

Use service-scoped cached builds. Avoid:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml build --no-cache queue
```

unless there is a concrete reason to invalidate the image cache.

---

## Lightweight vs Heavy Commands

Lightweight commands are OK from `web` or `queue` containers on Nodo0:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "..."

docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan <GENOME> \
  --results-tsv <TSV> \
  --datadir /app/targetpathogenweb/data
```

Examples of lightweight commands:

- `curated_pipeline_plan`
- `sync_genome_metadata`
- `import_external_results` when it loads existing files and is not computing
  pockets locally
- `load_ligq_2_results` for already-computed LigQ output
- `recompute_binder_directness`
- `backfill_curated_uniprot_annotations` (network/API-bound, not CPU-heavy)
- `fetch_experimental_structures --all-xrefs` (network/import-bound; can take
  time, but should not be confused with a SLURM-heavy computation)

Heavy commands must be remote/SLURM-backed:

- pipeline stages 10, 16, 17, and 24 when they compute InterProScan,
  ColabFold, structure pockets, or LigQ
- any full-proteome BLAST/HMMER/FastTarget job
- any full-proteome FPocket/P2Rank run

When in doubt, inspect the command. If it launches external scientific tools
over thousands of proteins, do not run it directly on Nodo0.

---

## Monitoring Remote SLURM Work

Run SLURM checks through the `queue` container using the configured SSH key:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "squeue -u $SSH_USERNAME"
'
```

Check a specific job:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "
sacct -j <JOBID> --format=JobID,JobName,State,ExitCode,Elapsed,NodeList -P
"
'
```

Inspect remote logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "
tail -80 <REMOTE_JOB_DIR>/slurm-<JOBID>.out
tail -80 <REMOTE_JOB_DIR>/slurm-<JOBID>.err
"
'
```

Important interpretation:

- The Django/UI stage banner may say a stage is pending or in progress while the
  real source of truth is the remote SLURM job.
- Always check `squeue`/`sacct` and the remote `slurm-*.out`/`slurm-*.err`
  before deciding a stage is stuck.
- If a stage reports `PENDING` for a long time, it may simply be waiting for a
  compute node. Do not restart blindly.
- If a remote job fails repeatedly on one node, compare `NodeList` across
  failures before blaming the input data.

Known operational note:

- LigQ_2/HMMER failed repeatedly on `nodo3` during the Kp13 work but succeeded
  on other nodes. Prefer `TPW_LIGQ_SLURM_EXCLUDE=nodo3` until `nodo3` is
  validated or fixed.

---

## Prerequisites

- Traefik running on Nodo0 (`internal-nodo0-web` network)
- Subdomain assigned by cluster admin (`TPW_DOMAIN`)
- Ports confirmed free: `18085` (web), `15433` (db), `13001` (jbrowse)
- SSH key for InterProScan remote jobs in `~/.ssh/`

---

## Steps

### 1. Clone the repo

```bash
cd /home/dockeradmin
git clone <repo_url> targetpathogenweb
cd targetpathogenweb
```

### 2. Environment file

```bash
cp .env.cluster.example .env
```

Fill in the required values:

```bash
# Generate secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Minimum required in `.env`:

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Generated above |
| `DJANGO_DATABASE_PASSWORD` | Strong password |
| `TPW_DB_PASSWORD` | Same as above |
| `TPW_DOMAIN` | Subdomain assigned by cluster admin |
| `DJANGO_ALLOWED_HOSTS` | Same domain + localhost |
| `SSH_HOSTNAME` | `cluster.qb.fcen.uba.ar` |
| `SSH_USERNAME` | Your cluster username |
| `SSH_WORKDIR` | Remote working dir for InterProScan |

### 3. Build and launch

```bash
make build ENV=cluster
make up ENV=cluster
```

First time only — check logs before going background:

```bash
# Terminal A: watch Traefik
cd /home/dockeradmin/nodo0-server
docker compose logs --tail=20 -f

# Terminal B: bring up the app
cd /home/dockeradmin/targetpathogenweb
make up ENV=cluster
```

### 4. Create admin user (first time only)

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec web python manage.py createsuperuser
```

Regular users are created from Django admin (`/admin/` → Users → Add user).

### 5. Verify

```bash
make status ENV=cluster
curl -v http://127.0.0.1:18085/health/live
```

---

## What happens automatically on startup

- Database migrations run (`start.sh` calls `migrate`)
- Static files are collected (cluster mode uses gunicorn + collectstatic)
- Queue worker picks up genome submissions automatically

---

## Day-to-day operations

```bash
make logs svc=web ENV=cluster       # web logs
make logs svc=queue ENV=cluster     # pipeline queue logs
make restart svc=web ENV=cluster    # restart web only
make status ENV=cluster             # container + volume status
```

Binder/LigQ_2 recovery, UniProt mapping, and direct-vs-homolog evidence loading are documented in [`docs/BINDERS_LIGQ2.md`](BINDERS_LIGQ2.md).
The curated Klebsiella import handoff and reusable curated-file workflow are documented in [`docs/KLEBSIELLA_CURATED_IMPORT.md`](KLEBSIELLA_CURATED_IMPORT.md).

### Copy large local files to Nodo0

Use the web upload panel for small files such as TSV/CSV/JSON. Large archives
such as structure or LigQ `.tar.gz` files can be rejected by the proxy with
`502 Bad Gateway` or `413 Request Entity Too Large`; copy them directly to the
shared data volume instead.

Recommended rule:

- small text files (`.tsv`, `.csv`, `.json`) → upload panel is fine
- large archives (`.tar.gz`, structure bundles, LigQ outputs, multi-GB files)
  → `scp` to Nodo0 and place under `/data/targetpathogen/data/uploads/`
- never store large project data only in container-local `/tmp`; container
  filesystems are disposable
- use `/tmp` only as a short-lived host staging area, then copy into
  `/data/targetpathogen/data/uploads/`

If Nodo0 is reachable directly from your workstation:

```bash
scp /local/path/Kp13.tar.gz dockeradmin@nodo0:/data/targetpathogen/data/uploads/
```

If only the cluster login node is reachable, stage through `cluster.qb.fcen.uba.ar`:

```bash
# From your workstation
scp /local/path/Kp13.tar.gz agutson@cluster.qb.fcen.uba.ar:/home/agutson/Kp13.tar.gz

# From cluster.qb.fcen.uba.ar
scp /home/agutson/Kp13.tar.gz glyco@nodo0:/tmp/Kp13.tar.gz
```

Then on Nodo0:

```bash
sudo mkdir -p /data/targetpathogen/data/uploads
sudo cp /tmp/Kp13.tar.gz /data/targetpathogen/data/uploads/
sudo chown dockeradmin:dockeradmin /data/targetpathogen/data/uploads/Kp13.tar.gz

cd /home/dockeradmin/targetpathogenweb
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ls -lh /app/targetpathogenweb/data/uploads/Kp13.tar.gz
'
```

Use the container path in management commands or the curated import form:

```text
/app/targetpathogenweb/data/uploads/Kp13.tar.gz
```

After copying a large archive, inspect it from inside the `queue` container
before extracting:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ls -lh /app/targetpathogenweb/data/uploads/<archive.tar.gz>
tar tzf /app/targetpathogenweb/data/uploads/<archive.tar.gz> | head -80
'
```

Extract only the directories needed for the import. Avoid expanding unrelated
multi-GB outputs into the shared volume unless they are required.

---

## IMPORTANT: never delete volumes

```bash
# SAFE — stops containers, keeps all data
make down ENV=cluster

# NEVER run this — deletes the database
# docker compose down -v
```

---

## Traefik labels

Domain is configured via `TPW_DOMAIN` in `.env`.
The Traefik network must be `internal-nodo0-web` (set via `TPW_EDGE_NETWORK`).
Router name `target2_nodo0` must be unique across all apps on the node.

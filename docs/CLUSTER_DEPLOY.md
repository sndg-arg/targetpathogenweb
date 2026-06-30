# Cluster Deployment Guide - Nodo0

This is the operational runbook for TargetPathogenWeb on Nodo0. Nodo0 is the
orchestration node: it hosts Docker services, Traefik routing, PostgreSQL, file
staging, and lightweight Django management commands. It is not a bioinformatics
compute node.

## Access

```bash
ssh agutson@cluster.qb.fcen.uba.ar
sudo su glyco
ssh nodo0
sudo su dockeradmin
cd /home/dockeradmin/targetpathogenweb
```

Important paths:

```text
/home/dockeradmin/targetpathogenweb   # repo checkout
/data/targetpathogen                  # persistent TPW data, never delete wholesale
/data/targetpathogen/data/uploads     # reviewed upload/staging files
```

## Nodo0 Rules

Allowed on Nodo0:

- `git pull`, `git status`, and normal repo inspection;
- service-scoped `make build ENV=cluster svc=<service>` and `make up ENV=cluster svc=<service>`;
- lightweight Django management commands inside `web` or `queue`;
- database metadata checks and coverage audits;
- importing already-computed TSV/JSON/PDB/mmCIF/pocket outputs;
- copying, moving, listing, and extracting reviewed files;
- monitoring local logs and remote SLURM jobs.

Do not run on Nodo0:

- full-proteome BLAST/HMMER/FastTarget searches;
- InterProScan;
- LigQ_2 computation;
- AlphaFold or ColabFold;
- full-proteome FPocket or P2Rank;
- large ad hoc scripts over all structures/sequences;
- `docker compose down -v`;
- `rm -rf /data/targetpathogen` or any broad destructive delete.

Rule of thumb: if a command launches scientific tools over thousands of proteins
or structures, run it through the TPW remote/SLURM wrapper, not directly on
Nodo0.

## Deploy Code

Default web deploy:

```bash
cd /home/dockeradmin/targetpathogenweb
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=web
make up ENV=cluster svc=web
```

Queue-only code changes:

```bash
cd /home/dockeradmin/targetpathogenweb
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=queue
make up ENV=cluster svc=queue
```

Use cached service-scoped builds. Avoid `--no-cache` unless debugging a concrete
image-cache problem.

## Lightweight Commands

Use `queue` for import/worker commands and `web` for web-specific checks:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan <GENOME> \
  --results-tsv <TSV> \
  --datadir /app/targetpathogenweb/data
```

Lightweight examples:

- `curated_pipeline_plan`
- `sync_genome_metadata`
- `import_external_results` when loading existing reviewed files
- `import_gates_pocket_outputs` when importing existing reviewed pocket outputs
- `load_ligq_2_results` for existing LigQ_2 output
- `recompute_binder_directness`
- small Django shell audits

Heavy work must be remote/SLURM-backed.

## Monitor Remote SLURM Work

Run checks through the `queue` container so the configured SSH key and username
are used consistently.

Queue for current user:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "squeue -u $SSH_USERNAME"
'
```

Specific job:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "
sacct -j <JOBID> --format=JobID,JobName,State,ExitCode,Elapsed,NodeList -P
"
'
```

Remote logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "
tail -80 <REMOTE_JOB_DIR>/slurm-<JOBID>.out
tail -80 <REMOTE_JOB_DIR>/slurm-<JOBID>.err
"
'
```

Interpretation rules:

- The UI may lag behind the real SLURM state. Trust `squeue`, `sacct`, and remote
  logs first.
- `PENDING` may simply mean the cluster is waiting for a suitable node.
- Compare `NodeList` across repeated failures before blaming input data.
- Do not restart jobs blindly while a remote process is still running.

## Copy Large Files To Nodo0

Use the web upload panel for small TSV/CSV/JSON files. Use direct file copy for
large archives; browser uploads can timeout or hit proxy limits.

If Nodo0 is reachable directly:

```bash
scp /local/path/Example.tar.gz dockeradmin@nodo0:/data/targetpathogen/data/uploads/
```

If only the cluster login node is reachable:

```bash
# Workstation -> cluster login
scp /local/path/Example.tar.gz agutson@cluster.qb.fcen.uba.ar:/home/agutson/Example.tar.gz

# Login node -> Nodo0 staging
scp /home/agutson/Example.tar.gz glyco@nodo0:/tmp/Example.tar.gz
```

Then on Nodo0:

```bash
sudo mkdir -p /data/targetpathogen/data/uploads
sudo cp /tmp/Example.tar.gz /data/targetpathogen/data/uploads/
sudo chown dockeradmin:dockeradmin /data/targetpathogen/data/uploads/Example.tar.gz
```

Verify from inside the container:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ls -lh /app/targetpathogenweb/data/uploads/Example.tar.gz
tar tzf /app/targetpathogenweb/data/uploads/Example.tar.gz | head -80
'
```

Use container paths in management commands:

```text
/app/targetpathogenweb/data/uploads/Example.tar.gz
```

## Extract Reviewed Archives

Prefer extracting only what the import needs. Extract the whole archive only when
it is the reviewed source bundle and disk space is acceptable.

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc '
cd /app/targetpathogenweb/data/uploads
tar xzf Example.tar.gz
ls -ld Example/structures
'
```

After extraction, confirm source folders exist before cleanup:

```bash
ls -ld /data/targetpathogen/data/uploads/<ARCHIVE_ROOT>/structures
```

## Cleanup Policy

Safe cleanup targets:

- duplicate archive copies in `/tmp`;
- duplicate archive copies in `uploads/` after extraction is verified;
- temporary import logs;
- failed partial staging folders that are known to be disposable.

Never delete:

- extracted reviewed source directories that may be needed for import/audit;
- TSVs used as source of truth;
- database volumes;
- `/data/targetpathogen` as a whole.

Fast checks:

```bash
df -h /
ls -ld /data/targetpathogen/data/uploads/<ARCHIVE_ROOT>/structures
sudo find /tmp -maxdepth 1 -type f \( -name "*.tar.gz" -o -name "import_gates_*.log" -o -name "*_gates_pockets*.log" \) -ls
sudo find /data/targetpathogen/data/uploads -maxdepth 1 -type f -size +500M -printf "%s %p\n" 2>/dev/null | sort -n
```

Avoid broad/deep `du` over `/data/targetpathogen`; it may traverse millions of
files and appear hung. Prefer scoped `find` commands over known staging paths.

## First-Time Cluster Setup

Use this only for a fresh Nodo0 install.

```bash
cd /home/dockeradmin
git clone <repo_url> targetpathogenweb
cd targetpathogenweb
cp .env.cluster.example .env
```

Required `.env` values:

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DATABASE_PASSWORD` | PostgreSQL password |
| `TPW_DB_PASSWORD` | Same PostgreSQL password |
| `TPW_DOMAIN` | Assigned cluster subdomain |
| `DJANGO_ALLOWED_HOSTS` | Domain plus localhost/internal hosts |
| `SSH_HOSTNAME` | Remote SLURM login host |
| `SSH_USERNAME` | Remote SLURM user |
| `SSH_WORKDIR` | Remote work directory |

Build and launch:

```bash
make build ENV=cluster
make up ENV=cluster
```

Create the first admin user:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec web python manage.py createsuperuser
```

Verify:

```bash
make status ENV=cluster
curl -v http://127.0.0.1:18085/health/live
```

## Daily Commands

```bash
make logs svc=web ENV=cluster
make logs svc=queue ENV=cluster
make restart svc=web ENV=cluster
make status ENV=cluster
make down ENV=cluster        # stops containers, keeps data
```

Never run:

```bash
docker compose down -v
```

## Related Docs

- [`CURATED_GENOME_IMPORT.md`](CURATED_GENOME_IMPORT.md): manual curator-first genome import.
- [`CURATED_FILE_IMPORT_AUTOMATION.md`](CURATED_FILE_IMPORT_AUTOMATION.md): staff/UI curated import flow.
- [`BINDERS_LIGQ2.md`](BINDERS_LIGQ2.md): LigQ_2 evidence and directness checks.
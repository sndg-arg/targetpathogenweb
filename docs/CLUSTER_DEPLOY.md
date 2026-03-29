# Cluster Deployment Checklist

Guide for deploying Target Pathogen to the cluster (SSH access).

This checklist only applies if IT gives you a host or dedicated node where Docker services may stay up permanently. It does not deploy the web stack into standard SLURM batch jobs. The pipeline already uses SLURM separately for remote stages such as InterProScan.

## Prerequisites

- Docker + Docker Compose installed on the cluster
- Traefik running as reverse proxy (already configured in compose labels)
- Enough disk to build the application image locally on the host. The first build is large because it bundles FastTarget databases and P2Rank assets.

## Steps

### 1. Environment file

Copy `.env.cluster.example` to `.env` on the cluster and fill in the security values:

```bash
cp .env.cluster.example .env
```

Generate a secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Set `DJANGO_SECRET_KEY` and `DJANGO_DATABASE_PASSWORD` in `.env`. These are required — the app will not start without them when `DJANGO_DEBUG=False`.

Optional production overrides:

- `TPW_DB_DIR` and `TPW_DATA_DIR` for persistent host storage
- `TPW_FASTTARGET_DB_DIR` for the shared FastTarget databases mounted read-only from the host
- `TPW_FASTTARGET_RUNTIME_DIR` and `TPW_FASTTARGET_LOG_DIR` for FastTarget outputs/logs
- `DJANGO_ROOT` for collected static files (`/app/staticfiles` by default)
- `JBROWSE_BASE_URL` for the browser URL (`http://localhost:3000/` by default)
- `SEQS_DATA_DIR` for sequence exports (`/app/targetpathogenweb/data/seqs` by default)
- `REDIS_URL` if you want Redis-backed cache instead of in-process cache
- `SENTRY_DSN` if you want Sentry error reporting
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` if outbound traffic on the host goes through a proxy

### 2. Launch

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml up --build -d
```

The cluster overlay (`docker-compose.cluster.yml`) automatically:
- Sets `TPW_PROFILE=cluster` → `start.sh` uses gunicorn instead of runserver
- Overrides DB password, secret key, allowed hosts from `.env`
- Uses the external Docker network from IT via `TPW_EDGE_NETWORK` (`internal-nodo0-web`)
- Mounts persistent runtime data from the host (`TPW_DB_DIR`, `TPW_DATA_DIR`), FastTarget databases/runtime dirs, plus SSH credentials when needed for remote SLURM jobs
- Bumps resource limits (4 GB RAM, 2 CPUs for web)
- Runs `collectstatic` on startup

### 3. Create admin user (first time only)

```bash
docker compose exec web python manage.py createsuperuser
```

Regular users are created from Django admin (`/admin/` → Users → Add user).

## What happens automatically

- Database migrations run on every startup (`start.sh` calls `migrate`)
- Static files are collected on startup in cluster mode
- The queue worker starts as a separate service and picks up genome submissions

## Traefik labels

The compose file has Traefik labels pointing to `target2.sbg.qb.fcen.uba.ar`.
If your domain is different, update the labels in `docker-compose.cluster.yml` and `DJANGO_ALLOWED_HOSTS` in `.env`.

## If QB only offers SLURM + Singularity

You still can use the cluster for heavy pipeline work, but not for the permanent web/db/queue/jbrowse stack with this compose setup. In that case you need one of these from IT:

- A dedicated host or service node with Docker/Compose for persistent containers
- A supported way to run long-lived services behind Traefik outside normal batch jobs
- An alternative deployment target for the web stack, while keeping SLURM for pipeline jobs

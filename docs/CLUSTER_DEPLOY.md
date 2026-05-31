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

### Copy large local files to Nodo0

Use the web upload panel for small files such as TSV/CSV/JSON. Large archives
such as structure or LigQ `.tar.gz` files can be rejected by the proxy with
`502 Bad Gateway` or `413 Request Entity Too Large`; copy them directly to the
shared data volume instead.

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

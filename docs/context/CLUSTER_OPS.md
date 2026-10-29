# Cluster operations (nodo0)

Moved out of `CLAUDE.md` so it only loads when needed.

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

### Checking ColabFold progress

**Remote GPU mode** (`TPW_COLABFOLD_USE_REMOTE=1`):
```bash
# Find the SLURM job ID from pipeline events:
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models import PipelineStageEvent
evt = PipelineStageEvent.objects.filter(app_name='colabfold_remote').order_by('-id').first()
print(evt.message, evt.payload)\""

# Check SLURM job status (replace JOB_ID):
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "sacct -j JOB_ID --format=JobID,State,Elapsed,ExitCode -P"

# Follow remote ColabFold log (replace JOB_DIR from payload):
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "tail -30 JOB_DIR/slurm-JOB_ID.out"

# Count PDBs produced so far on the remote node:
docker exec target2_nodo0_queue ssh -F /tmp/fakehome/.ssh/config -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster agutson@cluster.qb.fcen.uba.ar "ls JOB_DIR/output/*rank_001*.pdb 2>/dev/null | wc -l"
```

**Local CPU mode** (`TPW_COLABFOLD_USE_REMOTE=0`):
```bash
# Discover the temporary ColabFold directory:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "find /tmp -maxdepth 2 -type d -name 'colabfold_*' -print"

# Follow the ColabFold log:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "tail -f /tmp/colabfold_*/output/log.txt"

# Show the latest query only:
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec queue sh -lc "grep 'Query ' /tmp/colabfold_*/output/log.txt | tail -1"
```

**Both modes** — count final PDBs in workspace (replace ACC):
```bash
find /data/targetpathogen/data -path '*ACC/alphafold/*/*_af.pdb' | wc -l
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
from bioseq.models.Biodatabase import Biodatabase
Biodatabase.objects.filter(name__contains=u.accession).delete()
print(acc)\""

# Then remove only the matching on-disk paths (replace ACC with the value printed above):
ACC='public__ACCESSION_HERE'
MID=$(ACC="$ACC" python3 - <<'PY'
import math, os
acc = os.environ['ACC']
print(acc[math.floor(len(acc)/2 - 1):math.floor(len(acc)/2 + 2)])
PY
)
sudo rm -rf -- "/data/targetpathogen/data/${MID}/${ACC}"
sudo rm -rf -- "/data/targetpathogen/fasttarget_organism/${ACC}"
```

## Moving large files from neocranex to nodo0 (glyco's session eviction)

Staging a bulk download from the login node (neocranex) into nodo0's real data volume hit a
confusing failure mode this session (full-proteome AlphaFold structures, ~47K files, ~5GB) —
documented here since it'll recur for any future large transfer through `glyco`.

- **`glyco`'s writes vanish once the SSH connection that made them closes — but only for
  non-interactive invocations.** `rsync user@nodo0:path` or `ssh nodo0 "command"` writes data
  that's genuinely there *during that one connection*, then is gone (silently — no error, the
  path just doesn't exist on the next connection) the moment that connection ends. A command
  *typed directly at an already-open interactive `glyco@nodo0` shell prompt* does **not** have
  this problem and persists normally across full disconnect/reconnect — confirmed by writing a
  test file both ways and reconnecting fresh each time. This smells like a PAM session module
  (`pam_namespace` or similar) polyinstantiating storage for non-interactive exec/rsync-style
  SSH sessions specifically — never confirmed which module, but the behavioral split
  (interactive vs. non-interactive) is solid and reproducible.
  - Forcing a PTY (`ssh -t`) on an otherwise non-interactive command *also* makes the write
    persist — but routing `rsync` through it (`rsync -e "ssh -t" ...`) doesn't work: rsync
    owns the subprocess's stdin itself, so ssh sees "stdin is not a terminal" and can't actually
    allocate one, `-t` is silently ignored.
  - **`scp` (not `rsync`) sidesteps the whole problem** — a plain `scp -r source/
    glyco@nodo0:~/dest/` push persists fine across disconnects, confirmed both for persistence
    and byte-for-byte integrity (md5sum match) on a real `.gz` binary. Use `scp`, not `rsync`,
    for any glyco-mediated push to nodo0.
- **nodo0 has no outbound route back to neocranex** — `ip route` on nodo0 shows only its own
  public subnet and a pile of Docker bridge networks, nothing that reaches neocranex. The
  public hostname (`cluster.qb.fcen.uba.ar`) gets a TCP-level "Connection refused" from nodo0
  (likely a deliberate firewall rule — compute nodes aren't meant to call the login node back),
  and neocranex's *private* IP (192.168.0.1) isn't reachable either — it happens to also be
  nodo0's own gateway address on nodo0's side, so connecting to it from nodo0 loops back to
  nodo0 itself, not neocranex (classic RFC1918 address collision between two unrelated private
  networks). **Pulling from nodo0 doesn't work at all — only pushing from neocranex does.**
- **`glyco` isn't in the `clusterusers` group** that owns `agutson`'s home tree on
  `/storage/home/agutson` (NFSv3-mounted from `nas3`), and that NFSv3 mount **doesn't enforce
  POSIX ACLs** — `setfacl`/`getfacl` succeed and show the grant, but the server doesn't actually
  honor it, so adding `glyco` via ACL silently does nothing. The real fix: stage a copy
  somewhere with ordinary world-readable Unix permissions (e.g. `/tmp` on neocranex, default
  `drwxrwxrwt`) instead of trying to grant access on the NFS-mounted home directory.
  - `cp -r` **preserves source file permissions** — copying from a `0750`/`clusterusers`-group
    source into a freshly-`chmod 755`'d staging directory does *not* make the individual files
    inside world-readable, only the directory entry itself. Follow with an explicit
    `chmod -R o+rX <staging-dir>` on the files too, or reads of "most" files succeed while a
    scattered subset keeps failing with Permission denied depending on their original mode.
- **A `sudo mkdir -p` followed later by a plain `mkdir -p` on the same already-existing path is
  a no-op the second time** — ownership from the *first* call sticks. If that first call used
  `sudo`, the directory is root-owned, and a later non-sudo user (even `dockeradmin`, who isn't
  root) can't `chmod`/`chown` it without `sudo` too. `stat`/`getfacl` the destination before
  assuming "I made this dir, I must own it."

**Working recipe**, once a dataset is downloaded+extracted on neocranex (e.g. via
`scripts/cluster/fetch_human_proteome_bulk.sh`):
```bash
# On neocranex: make the staged copy genuinely world-readable (files, not just the dir)
chmod -R o+rX /path/to/staged_copy

# On nodo0, as dockeradmin: create the final destination first (sudo once, consistently)
sudo su dockeradmin
mkdir -p /data/targetpathogen/data/<name>   # no sudo here if the dir doesn't exist yet
chmod 777 /data/targetpathogen/data/<name>  # if a *previous* sudo mkdir left it root-owned
exit

# From neocranex, as glyco: scp (not rsync) to glyco's own home on nodo0
scp -r /path/to/staged_copy/ glyco@nodo0:~/staged_copy/

# On nodo0, as dockeradmin: move into the real, bind-mounted location
sudo su dockeradmin
cp -r /home/glyco/staged_copy/. /data/targetpathogen/data/<name>/
exit
```

## Importing external analysis results (Gates-Targets pipeline)

Use `import_external_results` to load pre-computed scores + structures into Target without re-running the full pipeline.

### 1. Load the genome first
Upload the `.gbk.gz` via the web UI (Genomes → Upload), let it run through stage 3 (load_gbk), then stop the pipeline.

### 2. Transfer files to the server

**glyco cannot write to `/data/targetpathogen/data/` directly** — use `/tmp/` on nodo0 as a staging area instead.

From cranex (after copying files there with scp from your Mac):
```bash
# TSV only (small — copy directly to the data volume via docker):
docker exec target2_nodo0_web bash -c "cat > /tmp/results_table.tsv" < results_table.tsv

# Large files (structures tar ~850MB) — scp to /tmp/ on nodo0, then access from container:
scp /home/agutson/ATCC43816_structures_only.tar.gz glyco@nodo0:/tmp/ATCC43816_structures_only.tar.gz
```

The container can read `/tmp/` on the host because nodo0's `/tmp/` is accessible from inside the container at the same path.

### 3. Extract the structures tar inside the container
```bash
docker exec target2_nodo0_queue bash -c "tar -xzf /tmp/ATCC43816_structures_only.tar.gz -C /tmp/"

# Verify extraction (check one PDB):
docker exec target2_nodo0_queue find /tmp -name "*.pdb" -maxdepth 6 | head -3
```

### 4. Run the import command
```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py import_external_results public__KpATCC43816 \
  --results-tsv /tmp/results_table.tsv \
  --structures-dir /tmp/KpATCC43816/structures \
  --datadir /app/targetpathogenweb/data \
  --overwrite"
```

Replace `public__KpATCC43816` with the actual internal accession (shown in the Genomes page URL or upload history). Adjust `--structures-dir` to match the actual extraction path.

### 5. Run remaining pipeline stages manually (optional)
After importing, stages that haven't run yet (UniProt mapping, binders, InterProScan) can still be kicked off via the web UI or management commands.

### Gates TSV → Target column mapping
| Gates column | Target ScoreParam |
|---|---|
| `human_offtarget` | `human_offtarget` |
| `druggability_score` | `Druggability` |
| `psortb_localization` | `Localization` |
| `gut_microbiome_offtarget_norm` | `gut_microbiome_offtarget_norm` |
| `gut_microbiome_offtarget_counts` | `gut_microbiome_offtarget_counts` |
| `colabfold_plddt` | `colabfold_plddt` |
| `core_roary` | `core_roary` |
| `core_corecruncher` | `core_corecruncher` |

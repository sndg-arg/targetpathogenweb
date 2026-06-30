# Curated Genome Import

This is the operational guide for loading a genome when curators/biologists
provide reviewed output files. The rule is **curators first**: if the reviewed
package contains a value, structure, pocket, binder, or annotation output, TPW
imports that source and does not recalculate it. Computation is used only for
missing data or for an explicit audit/rebuild request.

This guide is intentionally genome-agnostic. Record organism-specific facts in a
short task note or ticket, not in this workflow.

## Source Priority

Use this order for every curated import:

1. Reviewed `results_table.tsv` and reviewed per-stage files shipped by the
   curators.
2. Precomputed outputs inside the reviewed archive, including structures,
   FPocket/P2Rank pockets, off-target tables, essentiality, localization,
   conservation, Foldseek, and LigQ outputs when present.
3. TPW import/conversion of those reviewed files.
4. Pipeline or SLURM computation only for files absent from the reviewed package
   or for a requested supplemental rebuild.

For Gates-style structural packages, FPocket/P2Rank outputs live under
`structures/<gene>/pockets/`. Import them with `import_gates_pocket_outputs`.
Do not import ad-hoc recalculated SLURM pocket results when the reviewed package
already contains equivalent pocket outputs.

## Nodo0 Rules

Nodo0 is for orchestration and database loading. It is acceptable to run Django
management commands that import already-computed files. Do not run full-proteome
BLAST/HMMER, InterProScan, AlphaFold/ColabFold, FPocket, P2Rank, or LigQ_2
computation directly on Nodo0.

Use the repo on Nodo0:

```bash
cd /home/dockeradmin/targetpathogenweb
```

Deploy code changes with cached service-scoped builds:

```bash
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=queue
make up ENV=cluster svc=queue
```

Use `svc=web` instead when only web/UI code changed. Use full `make build
ENV=cluster` only when shared dependencies changed.

## Inputs

Expected reviewed package layout for Gates-style imports:

```text
<ARCHIVE_ROOT>/results_table.tsv          # sometimes delivered separately
<ARCHIVE_ROOT>/genome/                    # GBK/GBFF/GFF/FAA/FNA, depending on package
<ARCHIVE_ROOT>/structures/<gene>/         # ColabFold, AF DB, PDB chain structures
<ARCHIVE_ROOT>/structures/<gene>/pockets/ # FPocket/P2Rank reviewed outputs
<ARCHIVE_ROOT>/offtarget/                 # optional reviewed off-target outputs
<ARCHIVE_ROOT>/essentiality/              # optional reviewed essentiality outputs
<ARCHIVE_ROOT>/ligq2/ or LigQ_2/          # optional reviewed ligand outputs
```

The reviewed TSV must contain the expected locus column, usually `gene`, and its
locus tags must match an already loaded TPW proteome or the genome being loaded.

## Variables

Set these once per genome and reuse them in all commands:

```bash
GENOME=public__Example
GRAM=n
RESULTS_TSV=/app/targetpathogenweb/data/uploads/Example_results_table.tsv
ARCHIVE=/app/targetpathogenweb/data/uploads/Example.tar.gz
ARCHIVE_ROOT=Example
EXTRACT_DIR=/app/targetpathogenweb/data/uploads
STRUCTURES_DIR=$EXTRACT_DIR/$ARCHIVE_ROOT/structures
DATADIR=/app/targetpathogenweb/data
export GENOME GRAM RESULTS_TSV ARCHIVE ARCHIVE_ROOT EXTRACT_DIR STRUCTURES_DIR DATADIR
```

If the archive is already extracted in `uploads`, `EXTRACT_DIR` can be the
parent directory containing `$ARCHIVE_ROOT`.

## 1. Copy Large Files to Nodo0

Use the upload page for small TSV/CSV/JSON files. Copy multi-GB archives with
`scp`; web upload may timeout or hit proxy limits.

From your workstation to the cluster login node:

```bash
scp /local/path/Example.tar.gz agutson@cluster.qb.fcen.uba.ar:/home/agutson/Example.tar.gz
```

Then move it to Nodo0 and into the shared TPW data volume:

```bash
ssh agutson@cluster.qb.fcen.uba.ar
sudo su glyco
ssh nodo0
sudo su dockeradmin
cd /home/dockeradmin/targetpathogenweb
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

## 2. Extract Reviewed Files

For Gates-style packages used as source of truth, extracting the whole archive is
acceptable when the package is the reviewed data bundle and enough disk is
available. If the archive contains unrelated heavy folders, extract only the
needed directories.

Whole archive:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc '
cd /app/targetpathogenweb/data/uploads
tar xzf Example.tar.gz
ls -ld Example/structures
'
```

Selective extraction:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
set -euo pipefail
mkdir -p '$EXTRACT_DIR'
tar xzf '$ARCHIVE' -C '$EXTRACT_DIR' \
  '$ARCHIVE_ROOT/genome' \
  '$ARCHIVE_ROOT/structures' \
  '$ARCHIVE_ROOT/offtarget' \
  '$ARCHIVE_ROOT/essentiality'
find '$EXTRACT_DIR/$ARCHIVE_ROOT' -maxdepth 2 -type d | head -80
"
```

After extraction, confirm structures exist before deleting archive copies:

```bash
ls -ld /data/targetpathogen/data/uploads/<ARCHIVE_ROOT>/structures
```

## 3. Inspect Before Importing

Run fast checks only:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
head -3 '$RESULTS_TSV'
find '$STRUCTURES_DIR' -maxdepth 1 -type d | wc -l
find '$STRUCTURES_DIR' -maxdepth 3 -type d -name '*_fpocket' | head
find '$STRUCTURES_DIR' -maxdepth 3 -type d -name '*_p2rank' | head
"
```

Expected:

- TSV has the reviewed columns and locus tags.
- `structures/` contains one folder per reviewed protein.
- `pockets/` contains FPocket/P2Rank outputs when structural pockets are part of
  the reviewed package.

## 4. Load Genome Records When Needed

If the TPW genome/proteome does not exist yet, load genome records only and skip
heavy stages. Do not compute structures or pockets here.

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
DJANGO_SETTINGS_MODULE=tpwebconfig.settings \
/opt/conda/envs/tpv2/bin/python pipeline/run_pipeline_direct.py '$GENOME' \
  --genome-name '$GENOME' \
  --gram '$GRAM' \
  --custom '$EXTRACT_DIR/${ARCHIVE_ROOT}.gbk.gz' \
  --skip-stages 4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24 \
  --no-local-heavy
"
```

If the genome is already loaded, skip this step.

## 5. Import Reviewed Scores, Mapping, and Structures

Dry-run first:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --overwrite \
  --dry-run
```

Run for real:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --overwrite
```

This command loads TSV values, UniProt mapping where available, and reviewed
structure files. It should not be used as a substitute for reviewed pocket
geometry when the package has Gates `pockets/` output directories.

## 6. Import Reviewed Gates FPocket/P2Rank Outputs

Use this for packages with `structures/<gene>/pockets/`. It imports reviewed
FPocket/P2Rank output geometry and properties onto the matching TPW structure.
For PDB chain outputs, the matching reviewed chain structure is loaded and used,
so pocket surfaces are aligned to the displayed structure.

Dry-run first:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_gates_pocket_outputs "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --scope both \
  --force \
  --dry-run
```

Proceed only when the dry-run shows:

```text
Missing TPW structure: 0
Failed: 0
```

A small `Missing original output` count is acceptable only when the files are
absent from the reviewed package. Record those genes; do not silently
recalculate them.

Initial replacement import:

```bash
nohup docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_gates_pocket_outputs "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --scope both \
  --force \
  > /tmp/${GENOME}_gates_pockets.log 2>&1 &
```

`--force` is used only for the first replacement import, when replacing older
computed TPW pockets with reviewed Gates outputs.

If interrupted, resume without `--force`:

```bash
nohup bash -lc 'docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_gates_pocket_outputs "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --scope both 2>&1 \
  | grep --line-buffered -E "Gates pocket|Loaded pocket sets|Loaded missing structures|Skipped no-source|Skipped existing|Missing original output|Missing TPW structure|Failed|Examples|missing output|load failed|structure load failed|conversion failed|done loading pockets for:"' \
  > /tmp/${GENOME}_gates_pockets_resume.summary.log 2>&1 &
```

Monitor:

```bash
ps -eo pid,stat,etime,pcpu,pmem,args | grep import_gates_pocket_outputs | grep -v grep || true
tail -80 /tmp/${GENOME}_gates_pockets.log 2>/dev/null || true
tail -80 /tmp/${GENOME}_gates_pockets_resume.summary.log 2>/dev/null || true
```

## 7. Import Other Reviewed Outputs

Use package files instead of recomputing where available:

- off-target reviewed outputs: transform/load TPW score TSVs from `offtarget/`;
- essentiality reviewed outputs: transform/load from `essentiality/`;
- LigQ reviewed outputs: use `load_ligq_2_results` for already-computed output;
- UniProt/GO/EC/PDB reviewed mappings: use TSV mappings and backfill commands.

Only run remote SLURM stages for outputs not present in the package.

## 8. Validate

Plan should show no unexpected local-heavy work:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --datadir "$DATADIR"
```

For Gates-style pocket packages, selected PDB pocket validation must pass:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py selected_pdb_pocket_report "$GENOME"
```

Required final line:

```text
missing structure/pocket checks: 0
```

Expected `No_pockets` rows are acceptable when they come from the reviewed TSV.

## 9. Cleanup

After extraction and successful import, remove only disposable staging archives
and logs. Never delete extracted reviewed source directories, TSVs, database
volumes, or `/data/targetpathogen` wholesale.

Safe checks:

```bash
df -h /
ls -ld /data/targetpathogen/data/uploads/<ARCHIVE_ROOT>/structures
sudo find /tmp -maxdepth 1 -type f \( -name "*.tar.gz" -o -name "import_gates_*.log" -o -name "*_gates_pockets*.log" \) -ls
sudo find /data/targetpathogen/data/uploads -maxdepth 1 -type f -size +500M -printf "%s %p\n" 2>/dev/null | sort -n
```

Delete only reviewed, duplicate archive copies after confirming extraction:

```bash
sudo rm -f /tmp/<archive.tar.gz>
# Optional after review, if extracted source is present:
# sudo rm -f /data/targetpathogen/data/uploads/<archive.tar.gz>
```

Avoid deep `du` over `/data/targetpathogen`; it may traverse millions of files
and appear hung. Prefer `find` scoped to known staging folders and file names.

## Case Notes Template

For each curated genome, keep a short task note with:

```text
Genome:
Reviewed package:
Results TSV:
Extracted structures dir:
Commands run:
Missing original outputs intentionally not recalculated:
Validation command outputs:
Curator review notes:
```

Do not put large per-run count tables in this reusable guide. Counts change over
time and belong in task notes, logs, or final import reports.
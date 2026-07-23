# Curated Genome Import

This is the manual runbook for loading a genome from a reviewed package supplied
by curators or biologists. The core rule is simple: **the reviewed package is the
source of truth**. Target should import and convert reviewed values, structures,
pockets, binders, and annotations. It should compute only data that is absent
from the package or explicitly requested as a supplemental rebuild.

Use this guide for any organism. Keep organism names, exact paths, missing-file
lists, counts, and final command output in the ticket or task note.

## When To Use This

Use this runbook when you have at least one of:

- reviewed `results_table.tsv`;
- reviewed genome/proteome files;
- reviewed structure folders;
- reviewed FPocket/P2Rank output folders;
- reviewed off-target, essentiality, localization, conservation, Foldseek, or
  LigQ output.

Do not use this runbook to launch a full fresh Target computational pipeline. For a
fresh computational run, use the normal pipeline and SLURM-backed stages.

## Source Priority

Use this priority order for every curated import:

1. Reviewed TSV values and reviewed per-stage files shipped by the curators.
2. Precomputed outputs inside the reviewed archive.
3. Target conversion/import of those reviewed files.
4. Remote computation only for files absent from the reviewed package or for an
   explicit rebuild request.

Never import ad hoc recalculated outputs over equivalent reviewed outputs. Keep
those recalculations only as audit artifacts unless curators decide they replace
the original source.

## Stop Conditions

Stop and inspect before modifying production if any dry-run reports:

```text
Failed: nonzero
Missing Target structure: nonzero
missing structure/pocket checks: nonzero
```

`Missing original output` is different: it means the referenced reviewed file is
not present in the reviewed package. Record those genes and ask whether they are
intentionally absent; do not silently recalculate them.

## Variables

Set these once per genome. Use real values in the shell session, not in this doc.

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

Common paths:

```text
Host uploads:      /data/targetpathogen/data/uploads
Container uploads: /app/targetpathogenweb/data/uploads
Repo on Nodo0:     /home/dockeradmin/targetpathogenweb
```

## Reviewed Package Shape

A Gates-style package usually looks like this:

```text
<ARCHIVE_ROOT>/results_table.tsv
<ARCHIVE_ROOT>/genome/
<ARCHIVE_ROOT>/structures/<gene>/
<ARCHIVE_ROOT>/structures/<gene>/pockets/
<ARCHIVE_ROOT>/offtarget/
<ARCHIVE_ROOT>/essentiality/
<ARCHIVE_ROOT>/ligq2/ or <ARCHIVE_ROOT>/LigQ_2/
```

The TSV must have the expected locus column, usually `gene`, and those locus tags
must match the Target proteome or the genome being loaded.

## 1. Deploy The Import Code

Run this when code changed before the import:

```bash
cd /home/dockeradmin/targetpathogenweb
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=queue
make up ENV=cluster svc=queue
```

Use `svc=web` only for web/UI-only changes.

## 2. Copy Large Reviewed Files

Use the web upload page for small TSV/CSV/JSON files. Use `scp` for multi-GB
archives.

Workstation to cluster login node:

```bash
scp /local/path/Example.tar.gz agutson@cluster.qb.fcen.uba.ar:/home/agutson/Example.tar.gz
```

Login node to Nodo0 shared data volume:

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

Verify the container can see the archive:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ls -lh /app/targetpathogenweb/data/uploads/Example.tar.gz
tar tzf /app/targetpathogenweb/data/uploads/Example.tar.gz | head -80
'
```

## 3. Extract Reviewed Files

Whole reviewed source bundle:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc '
cd /app/targetpathogenweb/data/uploads
tar xzf Example.tar.gz
ls -ld Example/structures
'
```

Selective extraction when the archive has unrelated heavy folders:

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

Do not delete archive copies until the source folders exist and the import has
finished.

## 4. Preflight Checks

Run only bounded checks. Avoid deep recursive `du` over data volumes.

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
set -euo pipefail
head -3 '$RESULTS_TSV'
ls -ld '$STRUCTURES_DIR'
find '$STRUCTURES_DIR' -maxdepth 1 -type d | head
find '$STRUCTURES_DIR' -maxdepth 3 -type d -name '*_fpocket' | head
find '$STRUCTURES_DIR' -maxdepth 3 -type d -name '*_p2rank' | head
"
```

Expected result:

- TSV header is the reviewed file you intended to load.
- Structure directory exists.
- Pocket output folders exist if structural pockets are part of the reviewed
  package.

## 5. Load Genome Records If Missing

Skip this step if the Target genome/proteome already exists.

When only records are needed, skip heavy stages:

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

## 6. Import Reviewed TSV Values And Structures

Dry-run:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --overwrite \
  --dry-run
```

Execute:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --overwrite
```

This loads reviewed TSV values, UniProt mapping where available, and reviewed
structures. It does not replace the Gates pocket import step when reviewed
`pockets/` folders are present.

## 7. Import Reviewed Gates FPocket/P2Rank Outputs

Use this when `structures/<gene>/pockets/` contains reviewed FPocket/P2Rank
outputs. It imports the reviewed geometry and properties onto the same structure
used by the reviewed output. For PDB chain outputs, this avoids displaying pocket
surfaces against the wrong full PDB assembly.

Dry-run:

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

Proceed only when the dry-run has no unexpected structure/load failures.

First replacement import:

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

Use `--force` only for the intentional first replacement of older computed Target
pockets with reviewed outputs.

Interrupted import resume:

```bash
nohup bash -lc 'docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_gates_pocket_outputs "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --scope both 2>&1 \
  | grep --line-buffered -E "Gates pocket|Loaded pocket sets|Loaded missing structures|Skipped no-source|Skipped existing|Missing original output|Missing Target structure|Failed|Examples|missing output|load failed|structure load failed|conversion failed|done loading pockets for:"' \
  > /tmp/${GENOME}_gates_pockets_resume.summary.log 2>&1 &
```

Resume without `--force`; existing reviewed pocket sets are skipped.

Monitor:

```bash
ps -eo pid,stat,etime,pcpu,pmem,args | grep import_gates_pocket_outputs | grep -v grep || true
tail -80 /tmp/${GENOME}_gates_pockets.log 2>/dev/null || true
tail -80 /tmp/${GENOME}_gates_pockets_resume.summary.log 2>/dev/null || true
```

## 8. Import Other Reviewed Outputs

Use package files instead of recomputing when available:

- off-target reviewed outputs from `offtarget/`;
- essentiality reviewed outputs from `essentiality/`;
- localization, conservation, Foldseek, GO, EC, and UniProt mappings from the
  reviewed TSV/files;
- LigQ reviewed output with `load_ligq_2_results`.

Only launch remote computation for absent outputs.

## 9. Validate Closure

Plan/audit check:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --datadir "$DATADIR"
```

Selected PDB pocket check for Gates-style structural imports:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py selected_pdb_pocket_report "$GENOME"
```

Required final status:

```text
missing structure/pocket checks: 0
```

Expected `No_pockets` rows are acceptable only when they come from reviewed TSV
or reviewed source output.

## 10. Cleanup

After validation, remove only disposable staging files.

Safe checks:

```bash
df -h /
ls -ld /data/targetpathogen/data/uploads/<ARCHIVE_ROOT>/structures
sudo find /tmp -maxdepth 1 -type f \( -name "*.tar.gz" -o -name "import_gates_*.log" -o -name "*_gates_pockets*.log" \) -ls
sudo find /data/targetpathogen/data/uploads -maxdepth 1 -type f -size +500M -printf "%s %p\n" 2>/dev/null | sort -n
```

Delete only after confirming extraction/import:

```bash
sudo rm -f /tmp/<archive.tar.gz>
# Optional after review:
# sudo rm -f /data/targetpathogen/data/uploads/<archive.tar.gz>
```

Never delete extracted reviewed source folders, TSVs, database volumes, or
`/data/targetpathogen` wholesale.

## Task Note Template

Keep a short note per genome:

```text
Genome:
Reviewed package:
Results TSV:
Extracted source directories:
Import commands run:
Missing reviewed source outputs intentionally not recalculated:
Validation outputs:
Curator review notes:
```

Do not add per-run quantity tables to this reusable guide.
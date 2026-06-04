# Klebsiella Curated Import Handoff

This document records the curated Klebsiella imports performed on Nodo0 and
the operational findings needed to continue the work in a future session.

## Scope

Two curated Klebsiella genomes were loaded:

| Display name | TPW genome name | Proteome DB | Input TSV |
|--------------|-----------------|-------------|-----------|
| ATCC43816 | `public__KpATCC43816` | `public__KpATCC43816_prots` | `/app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv` |
| Kp13 | `public__KpKP13` | `public__KpKP13_prots` | `/app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv` |

All heavy work must run through SLURM compute nodes. Nodo0 is shared and must
only be used for Docker orchestration, database loading, small file movement,
and monitoring.

## Current Handoff Summary (2026-06-04)

Both curated Klebsiella genomes are loaded and usable for publication review.
The current branch is `file-ingestion`; the latest UI/logic changes for this
handoff were pushed through:

```text
4819532 Clarify experimental structure viewer UI
136b1c0 Fix experimental structure filtering
```

High-level status:

| Genome | Proteins | Curated structures | FPocket sets | P2Rank sets | UniProt mappings | EC proteins | GO proteins | PDB xref proteins | Experimental xrefs | Binders | ZINC/proposed |
|--------|----------|--------------------|--------------|-------------|------------------|-------------|-------------|-------------------|---------------------|---------|---------------|
| `public__KpATCC43816` | 5081 | 5080/5081 | 7906 | 15510 | 4805/5081 | 1140/5081 | 4002/5081 | 83/5081 | 201 | 150298 | 112749 |
| `public__KpKP13` | 5842 | 5840/5842 | 8794 | 16429 | 5368/5842 | 1151/5842 | 4132/5842 | 72/5842 | 258 | 151153 | 113400 |

Pipeline status for both genomes:

```text
Heavy stages that still require SLURM: -
```

Important interpretation:

- "Curated structures" are local model/structure files used by the TPW 3D
  viewer and pocket overlays. For these Klebsiella datasets they are mostly
  ColabFold/curated predicted structures.
- "PDB xrefs" / "Experimental xrefs" are UniProt-derived experimental PDB
  evidence with method, resolution, chains, and residue coverage. These entries
  do not necessarily cover the whole protein.
- "Loaded experimental structures" are experimental PDB files that were also
  downloaded and loaded into TPW so the 3D viewer can render them.
- Experimental PDB structures and predicted models must be interpreted
  separately. Predicted models are usually full-length; experimental structures
  are often fragments.

Loaded experimental PDB status after `fetch_experimental_structures --all-xrefs`:

| Genome | Xref entries | Xref proteins | Loaded experimental links | Loaded experimental proteins | Loaded PDB codes | Missing PDB codes |
|--------|--------------|---------------|---------------------------|------------------------------|------------------|-------------------|
| `public__KpATCC43816` | 201 | 83 | 199 | 81 | 193/195 | 2 |
| `public__KpKP13` | 258 | 72 | 252 | 70 | 247/253 | 6 |
| `public__NC_002516.2` | 2293 | 707 | 2229 | 701 | 2139/2201 | 62 |
| `public__NZ_AP023069.1` | 19 | 3 | 19 | 3 | 19/19 | 0 |

Known missing experimental PDB codes for Klebsiella:

```text
public__KpATCC43816:
  VK055_4658 8ORR X-RAY 1.68 chains AAA positions 31-392
  VK055_4699 6UE0 X-RAY 1.89 chains AAA,BBB positions 1-292

public__KpKP13:
  KP13_00864 8ORR X-RAY 1.68 chains AAA positions 31-392
  KP13_03824 6UE0 X-RAY 1.89 chains AAA,BBB positions 1-292
  KP13_06703 8RWR X-RAY 1.03 chain A positions 25-293
  KP13_06703 9FBT X-RAY 1.07 chain A positions 25-293
  KP13_06703 8RWP X-RAY 1.19 chain A positions 25-293
  KP13_06703 8AKM X-RAY 1.25 chain A positions 25-293
```

These missing rows are still visible as metadata-only evidence if their xrefs
exist. They were not locally renderable after the automated load, likely due to
PDB parser/download/chain-format limitations rather than absent evidence.

Direct ligand evidence after recomputing directness from UniProt mappings:

| Genome | PDB direct | ChEMBL direct | PDB homolog | ChEMBL homolog | ZINC/proposed |
|--------|------------|---------------|-------------|----------------|---------------|
| `public__KpATCC43816` | 71 | 1 | 17937 | 19540 | 112749 |
| `public__KpKP13` | 124 | 4 | 18225 | 19400 | 113400 |

Product/UI status:

- Genome list now separates loaded experimental structures from PDB xrefs.
- Protein table filtering by `Structure: Experimental` was fixed to use an
  `Exists` subquery, because the previous multi-relation `exclude()` removed
  proteins that had both experimental PDBs and ColabFold models.
- Protein table structure labels now show `Experimental + predicted` when both
  evidence types exist.
- Protein detail now has an "Experimental structures" table with PDB ID,
  method, resolution, chain, positions, coverage, links, and loaded/viewer
  status.
- The 3D viewer selector now labels loaded experimental entries as
  `PDB <id> · <coverage> · <resolution>` and marks which PDB row is currently
  shown below.

## Quick Start for a Future Chat

When resuming this work, start with these checks from Nodo0. They are light
database/metadata checks and should not run heavy bioinformatics on Nodo0.

```bash
cd ~/targetpathogenweb
git branch --show-current
git log --oneline -5
git status --short
```

Confirm the deployed code includes the latest handoff commits:

```bash
git log --oneline --decorate -10
```

Expected relevant commits near the top of `file-ingestion`:

```text
4819532 Clarify experimental structure viewer UI
136b1c0 Fix experimental structure filtering
23e5762 Allow loading all experimental PDB xrefs
8a43305 Show PDB xref evidence separately from loaded structures
66569ec Add binder directness recompute command
b12b21c Add curated UniProt backfill and PDB coverage UI
```

If the code is behind:

```bash
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=web
make up ENV=cluster svc=web
```

Re-run the curated plans:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan public__KpATCC43816 \
  --results-tsv /app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv \
  --datadir /app/targetpathogenweb/data

docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan public__KpKP13 \
  --results-tsv /app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv \
  --datadir /app/targetpathogenweb/data
```

Expected for both:

```text
Heavy stages that still require SLURM: -
```

If direct ligand counts look wrong after any reload, recompute directness:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py recompute_binder_directness public__KpATCC43816

docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py recompute_binder_directness public__KpKP13
```

If EC/GO/PDB xrefs look missing after a reload, backfill from the curated TSVs:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py backfill_curated_uniprot_annotations public__KpATCC43816 \
  --results-tsv /app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv \
  --datadir /app/targetpathogenweb/data \
  --overwrite-mapping

docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py backfill_curated_uniprot_annotations public__KpKP13 \
  --results-tsv /app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv \
  --datadir /app/targetpathogenweb/data \
  --overwrite-mapping
```

If experimental PDBs are metadata-only and need local 3D rendering, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py fetch_experimental_structures public__KpATCC43816 \
  --datadir /app/targetpathogenweb/data \
  --all-xrefs

docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py fetch_experimental_structures public__KpKP13 \
  --datadir /app/targetpathogenweb/data \
  --all-xrefs
```

## Nodo0 Operating Pattern

Use the repo on Nodo0:

```bash
cd ~/targetpathogenweb
```

Use cached service-scoped builds when deploying code changes:

```bash
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=web
make up ENV=cluster svc=web
```

For queue-only changes:

```bash
git pull --ff-only origin file-ingestion
make build ENV=cluster svc=queue
make up ENV=cluster svc=queue
```

Do not use `--no-cache` unless there is a specific image corruption problem.
Do not run HMMER, LigQ_2, InterProScan, FPocket, P2Rank, AlphaFold, or
ColabFold directly on Nodo0.

## Reusable Curated Genome Workflow

Use this section when repeating the curated-file import for another genome.
Replace the variables in the first block and then run the commands step by step.

Example variables:

```bash
GENOME=public__KpKP13
GRAM=n
RESULTS_TSV=/app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv
ARCHIVE=/app/targetpathogenweb/data/uploads/Kp13.tar.gz
EXTRACT_DIR=/app/targetpathogenweb/data/imports/Klebsiella/Kp13
ARCHIVE_ROOT=KpKP13
STRUCTURES_DIR=$EXTRACT_DIR/$ARCHIVE_ROOT/structures
DATADIR=/app/targetpathogenweb/data
```

### 1. Put files in the shared data volume

Small TSV/CSV/JSON files can be uploaded from the UI. Large `.tar.gz` archives
should be copied directly into the shared volume because Traefik/proxy uploads
can fail with `500`, `502`, or request-size limits.

Expected container paths:

```text
/app/targetpathogenweb/data/uploads/<results_table.tsv>
/app/targetpathogenweb/data/uploads/<archive.tar.gz>
```

See `docs/CLUSTER_DEPLOY.md` for the `scp` staging pattern through the cluster
login node.

### 2. Inspect the archive before extracting

Do this inside the `queue` container:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
tar tzf '$ARCHIVE' | awk -F/ 'NF>=2 {print \$1\"/\"\$2}' | sort | uniq -c | sort -nr | head -80
tar tzf '$ARCHIVE' | grep -Ei '(\\.gbk$|\\.gbk\\.gz$|\\.gbff$|\\.gff$|\\.faa$|\\.fna$|results_table\\.tsv$|_af\\.pdb$|fpocket\\.json|p2pocket\\.json)' | head -200
head -3 '$RESULTS_TSV'
"
```

Confirm:

- the top-level archive folder (`ARCHIVE_ROOT`)
- the GBK/GBFF file
- structure directory layout
- TSV columns and locus tag format

### 3. Extract only the needed directories

Avoid extracting unrelated huge folders unless needed:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
set -euo pipefail
mkdir -p '$EXTRACT_DIR'
tar xzf '$ARCHIVE' -C '$EXTRACT_DIR' \
  '$ARCHIVE_ROOT/genome' \
  '$ARCHIVE_ROOT/structures' \
  '$ARCHIVE_ROOT/offtarget' \
  '$ARCHIVE_ROOT/essentiality'
find '$EXTRACT_DIR/$ARCHIVE_ROOT/genome' -maxdepth 1 -type f -ls
"
```

If the GBK is uncompressed, create a `.gbk.gz` copy:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
gbk=\$(find '$EXTRACT_DIR/$ARCHIVE_ROOT/genome' -maxdepth 1 -type f \\( -name '*.gbk' -o -name '*.gbff' \\) | head -1)
gzip -c \"\$gbk\" > '$EXTRACT_DIR/${ARCHIVE_ROOT}.gbk.gz'
ls -lh '$EXTRACT_DIR/${ARCHIVE_ROOT}.gbk.gz'
"
```

### 4. Load the genome records only

Run stages 2/3 and skip everything heavy. If a previous partial load exists,
inspect DB counts first before reloading.

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

If `sync_genome_metadata` fails but records loaded, run it explicitly:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py sync_genome_metadata \
  "$GENOME" "$DATADIR/<computed-folder>/$GENOME.gbk.gz"
```

The computed folder can be found with:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --datadir "$DATADIR"
```

### 5. Import curated TSV scores, UniProt mapping, structures

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

Then run for real:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --structures-dir "$STRUCTURES_DIR" \
  --datadir "$DATADIR" \
  --overwrite
```

If pocket JSON loading is intentionally deferred to the remote stage, use the
appropriate import option to skip pockets and preserve curated structures.

### 6. Post-process existing FastTarget-like outputs

If curated `offtarget/` files are present, generate/load the TPW score TSVs
instead of running FastTarget from scratch. The exact command depends on the
available archive layout. After post-processing, run stage 5/7 loaders only:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
DJANGO_SETTINGS_MODULE=tpwebconfig.settings \
/opt/conda/envs/tpv2/bin/python pipeline/run_pipeline_direct.py '$GENOME' \
  --genome-name '$GENOME' \
  --gram '$GRAM' \
  --start-stage 5 \
  --skip-stages 4,6,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24 \
  --no-local-heavy
"
```

Re-run `curated_pipeline_plan` and confirm scores such as `human_offtarget` and
`hit_in_deg` are complete.

### 7. Run required remote stages

The plan tells you what still requires SLURM:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan "$GENOME" \
  --results-tsv "$RESULTS_TSV" \
  --datadir "$DATADIR"
```

Typical curated-file resume command after scores/structures are imported:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
DJANGO_SETTINGS_MODULE=tpwebconfig.settings \
nohup /opt/conda/envs/tpv2/bin/python pipeline/run_pipeline_direct.py '$GENOME' \
  --genome-name '$GENOME' \
  --gram '$GRAM' \
  --start-stage 10 \
  --skip-stages 4,5,6,7,8,9,15,16,18,19,20,21,22,23 \
  --no-local-heavy \
  > /tmp/${GENOME}_curated_pipeline_resume10.log 2>&1 &
echo \$!
"
```

Monitor:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc "
tail -f /tmp/${GENOME}_curated_pipeline_resume10.log
"
```

Check SLURM from the container:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "squeue -u agutson"
'
```

### 8. Run LigQ_2 as stage 24

For now, avoid `nodo3` for LigQ_2:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue bash -lc "
DJANGO_SETTINGS_MODULE=tpwebconfig.settings \
TPW_LIGQ_SLURM_EXCLUDE=nodo3 \
nohup /opt/conda/envs/tpv2/bin/python pipeline/run_pipeline_direct.py '$GENOME' \
  --genome-name '$GENOME' \
  --gram '$GRAM' \
  --start-stage 24 \
  --skip-stages 4,5,6,7,8,9,10,11,15,16,17,18,19,20,21,22,23 \
  --no-local-heavy \
  > /tmp/${GENOME}_curated_pipeline_ligq.log 2>&1 &
echo \$!
"
```

Do not use `TPW_LIGQ_EXCLUDE_LOCI` unless the same locus fails on multiple
non-`nodo3` compute nodes.

### 9. Final audit

The final plan should have no heavy stages remaining:

```text
Heavy stages that still require SLURM: -
```

Run binder counts:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from django.db.models import Count
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
db=Biodatabase.objects.get(name='${GENOME}_prots')
qs=Binders.objects.filter(locustag__biodatabase=db)
print('binders total', qs.count())
print('by source', list(qs.values('source').annotate(n=Count('id')).order_by('source')))
print('proteins with binders', qs.values('locustag_id').distinct().count())
"
```

## ATCC43816 Final State

Final audit command:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan public__KpATCC43816 \
  --results-tsv /app/targetpathogenweb/data/imports/Klebsiella/results_table.tsv \
  --datadir /app/targetpathogenweb/data
```

Expected final state:

- Proteins: `5081`
- Scores: all imported scores at `5081/5081`
- Structures: `5080/5081`
- FPocket pocket sets: `7906`
- P2Rank pocket sets: `15510`
- InterPro features: `4850/5081`
- UniProt mappings: `4805/5081`
- GO/EC annotations: `4002/5081`
- EC annotations: `1140/5081`
- GO annotations: `4002/5081`
- PDB xref proteins: `83/5081`
- Experimental structure xrefs: `201`
- Binder rows: `150298`
- LigQ/ZINC binder rows: `112749`
- Heavy stages still required: `-`

Binder breakdown:

```text
chembl:   19541  (1 direct, 19540 via homolog)
pdb:      18008  (71 direct, 17937 via homolog)
proposed: 112749
proteins with binders: 2722
```

Notes:

- Stage 15/16 are skipped intentionally because curated structures cover
  almost the full proteome and should be preserved.
- LigQ_2 completed successfully after avoiding `nodo3`.

## Kp13 Final State

Input files:

```text
/app/targetpathogenweb/data/uploads/Kp13.tar.gz
/app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv
```

Selected archive contents were extracted under:

```text
/app/targetpathogenweb/data/imports/Klebsiella/Kp13/KpKP13/
```

The loaded TPW genome is:

```text
public__KpKP13
```

Final audit command:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py curated_pipeline_plan public__KpKP13 \
  --results-tsv /app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv \
  --datadir /app/targetpathogenweb/data
```

Expected final state:

- Proteins: `5842`
- Scores: all imported scores at `5842/5842`
- Structures: `5840/5842`
- FPocket pocket sets: `8794`
- P2Rank pocket sets: `16429`
- InterPro TSV exists: `True`
- Sequence features: `5289/5842`
- UniProt mapping: `5368/5842`
- GO/EC annotations: `4132/5842`
- EC annotations: `1151/5842`
- GO annotations: `4132/5842`
- PDB xref proteins: `72/5842`
- Experimental structure xrefs: `258`
- Binder rows: `151153`
- LigQ/ZINC binder rows: `113400`
- Heavy stages still required: `-`

Binder breakdown:

```text
chembl:   19404  (4 direct, 19400 via homolog)
pdb:      18349  (124 direct, 18225 via homolog)
proposed: 113400
proteins with binders: 2736
```

The only expected warning is:

```text
Curated structures cover 5840/5842 proteins; stages 15/16 are still skipped to preserve curated structures.
```

## Kp13 Load Sequence

The GBK was extracted from the uploaded archive and loaded as
`public__KpKP13`. Multi-record genome metadata required
`sync_genome_metadata` support for multi-record GBK files.

Metadata sync result:

```text
EntryLength=5739888
COUNT_gene=5973
COUNT_CDS=5842
COUNT_tRNA=86
COUNT_rRNA=24
COUNT_ncRNA=0
COUNT_tmRNA=0
```

External curated results were imported with:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py import_external_results public__KpKP13 \
  --results-tsv /app/targetpathogenweb/data/uploads/KpKP13_results_table.tsv \
  --structures-dir /app/targetpathogenweb/data/imports/Klebsiella/Kp13/KpKP13/structures \
  --datadir /app/targetpathogenweb/data \
  --overwrite
```

FastTarget-like files were post-processed from the curated archive:

```text
/app/targetpathogenweb/data/imports/Klebsiella/Kp13/KpKP13/offtarget/human_offtarget.tsv
/app/targetpathogenweb/data/imports/Klebsiella/Kp13/KpKP13/offtarget/human_offtarget_blast.tsv
```

The fallback essentiality file generated for Kp13 was:

```text
/app/targetpathogenweb/data/__K/public__KpKP13/essenciality.tsv
```

InterProScan and structure-pocket prediction were run remotely through SLURM.
The final structure-pocket remote job completed with:

```text
proteins   5840
fpocket_ok 5840
p2rank_ok  5840
failures   0
```

## LigQ_2 / HMMER Issue: Root Cause and Resolution

Initial LigQ_2 retries for Kp13 failed with:

```text
Fatal exception (source file fwdback.c, line 457):
forward score is NaN
```

The failing command inside LigQ_2 was:

```bash
hmmscan --cpu 4 --noali \
  --domtblout temp_results/hmmer_pfam_domtblout.txt \
  --cut_ga databases/complementary_databases/pfam/Pfam-A.hmm \
  proteins.fasta
```

At first, a per-protein pre-screen on `nodo3` identified 35 loci that triggered
the HMMER abort. However, deeper testing showed those proteins are not
intrinsically invalid:

- The sequences contain standard amino-acid letters.
- They are enriched for hydrophobic/transmembrane-like content, but that is not
  sufficient to explain the failure.
- The same proteins passed on `sauron` with HMMER 3.4 and HMMER 3.3.
- All failed LigQ_2 attempts for Kp13 ran on `nodo3`.
- Earlier failed LigQ_2 attempts for ATCC43816 also ran on `nodo3`.
- A successful ATCC43816 LigQ_2 run ran on `nodo4`.

Conclusion:

```text
The problem is operationally tied to nodo3 and/or its HMMER runtime behavior,
not to specific bad proteins in the curated proteome.
```

Do not exclude the 35 loci for the final Kp13 run. The successful Kp13 run used
the full proteome and excluded only `nodo3` from SLURM:

```bash
TPW_LIGQ_SLURM_EXCLUDE=nodo3
```

Successful Kp13 LigQ_2 load summary:

```text
known: raw=47416  kept=37753  written=37753  missing_locustag=0
zinc:  raw=213483 kept=113400 written=113400 missing_locustag=0
```

Recommended future policy:

- For LigQ_2 jobs, set `TPW_LIGQ_SLURM_EXCLUDE=nodo3` unless `nodo3` is fixed
  or validated.
- If HMMER errors recur, first check `sacct` node placement before excluding
  proteins.
- Only use `TPW_LIGQ_EXCLUDE_LOCI` as a last resort after confirming the same
  loci fail reproducibly on multiple compute nodes.

## Useful Diagnostics

Check current jobs:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "squeue -u agutson"
'
```

Check a completed SLURM job:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
ssh -F /dev/null -i "$SSH_KEY_FILENAME" -o IdentitiesOnly=yes \
  "$SSH_USERNAME@$SSH_HOSTNAME" "
sacct -j <JOBID> --format=JobID,JobName,State,ExitCode,Elapsed,NodeList -P
"
'
```

Check LigQ_2 output counts:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue sh -lc '
dir=/app/targetpathogenweb/data/__K/public__KpKP13/ligq2/output
echo known=$(find "$dir" -type f -name known_ligands.tsv | wc -l)
echo predicted=$(find "$dir" -type f -name predicted_ligands.tsv | wc -l)
echo zinc=$(find "$dir" -type f -name zinc_ligands.tsv | wc -l)
ls -lh "$dir/search_results_summary.tsv"
'
```

Check binder counts:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from django.db.models import Count
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
db=Biodatabase.objects.get(name='public__KpKP13_prots')
qs=Binders.objects.filter(locustag__biodatabase=db)
print('binders total', qs.count())
print('by source', list(qs.values('source').annotate(n=Count('id')).order_by('source')))
print('proteins with binders', qs.values('locustag_id').distinct().count())
"
```

Check direct versus homolog binder classification:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from django.db.models import Count
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders

for genome in ['public__KpATCC43816', 'public__KpKP13']:
    db = Biodatabase.objects.get(name=genome + Biodatabase.PROT_POSTFIX)
    qs = Binders.objects.filter(locustag__biodatabase=db)
    print('\\n===', genome, '===')
    print('total', qs.count())
    print('by source/direct', list(qs.values('source', 'is_direct').annotate(n=Count('id')).order_by('source', 'is_direct')))
    print('direct pdb+chembl', qs.filter(source__in=['pdb', 'chembl'], is_direct=True).count())
    print('via homolog pdb+chembl', qs.filter(source__in=['pdb', 'chembl'], is_direct=False).count())
    print('zinc proposed', qs.filter(source='proposed').count())
"
```

## Follow-up: EC Numbers and Other Missing Annotation Values

The curated Klebsiella TSVs did not include EC numbers directly. EC values in
TPW are expected to come from UniProt annotation fetching (`stage 13` /
`fetch_uniprot_annotations`) after a valid UniProt mapping exists.

Before backfilling, check exact EC and GO counts separately:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref
for genome in ['public__KpATCC43816', 'public__KpKP13']:
    db=Biodatabase.objects.get(name=genome + Biodatabase.PROT_POSTFIX)
    qs=BioentryDbxref.objects.filter(bioentry__biodatabase=db)
    print(genome)
    print('  UniProt mapped proteins', qs.filter(dbxref__dbname__in=['UnipSp','UnipTr']).values('bioentry_id').distinct().count())
    print('  EC proteins', qs.filter(dbxref__dbname__in=['ec','EC']).values('bioentry_id').distinct().count())
    print('  GO proteins', qs.filter(dbxref__dbname__in=['go','GO']).values('bioentry_id').distinct().count())
    print('  PDB xref proteins', qs.filter(dbxref__dbname='PDB').values('bioentry_id').distinct().count())
"
```

If EC is missing but the TSV has UniProt accessions, use the combined
curated backfill command. It imports/reimports the TSV UniProt mappings,
writes the `{genome}_unips.lst` file, then fetches UniProt EC, GO, and PDB
cross-reference metadata:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py backfill_curated_uniprot_annotations <GENOME> \
  --results-tsv <RESULTS_TSV> \
  --datadir /app/targetpathogenweb/data \
  --overwrite-mapping
```

Dry-run the mapping part first when using a new TSV:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py backfill_curated_uniprot_annotations <GENOME> \
  --results-tsv <RESULTS_TSV> \
  --datadir /app/targetpathogenweb/data \
  --overwrite-mapping \
  --dry-run
```

This command can add:

- EC dbxrefs
- GO dbxrefs
- PDB cross-references into `ExperimentalStructureXref`

It uses the UniProt REST API, so it is network-bound rather than CPU-heavy. It
is acceptable to run from the queue container, but it should still be monitored
and not confused with SLURM-heavy work.

For the final Klebsiella state, both genomes have current `UnipSp` / `UnipTr`
links and UniProt-derived EC/GO/PDB metadata. If direct-vs-homolog binder
classification looks wrong after reloading LigQ, run
`recompute_binder_directness` after confirming UniProt mappings exist.

## Experimental PDB Structures and Partial Coverage UI

The current code supports experimental PDB evidence separately from predicted
models:

- `ExperimentalStructureXref` stores `pdb_id`, `method`, `resolution`, `chains`,
  `uniprot_start`, and `uniprot_end`.
- `BioentryStructure` also stores `chain`, `uniprot_start`, `uniprot_end`, and
  `resolution`.
- `backfill_curated_uniprot_annotations` imports curated UniProt mappings and
  fetches UniProt-derived EC, GO, and PDB cross-reference metadata.
- `fetch_experimental_structures --all-xrefs` downloads/loads all PDB xrefs it
  can parse, not only the best experimental structure per protein.
- The genome list separates loaded experimental structures from PDB xref
  metadata.
- The protein list filter `Structure: Experimental` returns proteins with at
  least one local experimental PDB structure, even when they also have
  AlphaFold/ColabFold models.
- The protein detail page shows an "Experimental structures" table similar in
  spirit to UniProt's Structure section: source, PDB ID, method, resolution,
  chain, positions, coverage, external links, and loaded/viewer status.
- The 3D viewer selector labels experimental choices by PDB ID, coverage, and
  resolution, for example `PDB 7CZ9 · 99.2% · 1.85 A`.

The key interpretation remains:

```text
Experimental PDB structures often cover only part of the protein.
Do not treat an experimental PDB xref as full-length coverage unless its
positions/coverage show that.
```

Load all experimental PDB xrefs for a genome:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T queue \
  /opt/conda/envs/tpv2/bin/python manage.py fetch_experimental_structures <GENOME> \
  --datadir /app/targetpathogenweb/data \
  --all-xrefs
```

This command downloads PDB files over the network and imports them into the
database. It is not a SLURM-heavy stage, but it can take time and should be run
from the container, not as a CPU-heavy process on Nodo0.

Audit experimental PDB metadata versus loaded local structures:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref

for genome in ['public__KpATCC43816', 'public__KpKP13', 'public__NC_002516.2', 'public__NZ_AP023069.1']:
    db = Biodatabase.objects.get(name=genome + Biodatabase.PROT_POSTFIX)
    xrefs = ExperimentalStructureXref.objects.filter(bioentry__biodatabase=db)
    loaded = BioentryStructure.objects.filter(bioentry__biodatabase=db).exclude(pdb__experiment__in=['AF', 'CF'])
    xref_codes = set(xrefs.values_list('pdb_id', flat=True))
    loaded_codes = set(loaded.values_list('pdb__code', flat=True))
    print('\\n===', genome, '===')
    print('xref entries:', xrefs.count())
    print('xref proteins:', xrefs.values('bioentry_id').distinct().count())
    print('loaded experimental links:', loaded.count())
    print('loaded experimental proteins:', loaded.values('bioentry_id').distinct().count())
    print('loaded xref PDB codes:', len(xref_codes & loaded_codes), '/', len(xref_codes))
    print('missing xref PDB codes:', len(xref_codes - loaded_codes))
    print('extra loaded experimental codes not in xrefs:', len(loaded_codes - xref_codes))
"
```

List missing experimental PDB xrefs:

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster.yml exec -T web \
  /opt/conda/envs/tpv2/bin/python manage.py shell -c "
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref

for genome in ['public__KpATCC43816', 'public__KpKP13', 'public__NC_002516.2']:
    db = Biodatabase.objects.get(name=genome + Biodatabase.PROT_POSTFIX)
    loaded_codes = set(BioentryStructure.objects.filter(
        bioentry__biodatabase=db,
    ).exclude(pdb__experiment__in=['AF', 'CF']).values_list('pdb__code', flat=True))
    missing = ExperimentalStructureXref.objects.filter(
        bioentry__biodatabase=db,
    ).exclude(pdb_id__in=loaded_codes).select_related('bioentry').order_by('bioentry__accession', 'resolution')
    print('\\n===', genome, 'missing', missing.count(), '===')
    for x in missing:
        print(x.bioentry.accession, x.pdb_id, x.method, x.resolution, x.chains, x.uniprot_start, x.uniprot_end)
"
```

## Relevant Code Changes

These commits on `file-ingestion` are relevant to this work:

```text
4819532 Clarify experimental structure viewer UI
136b1c0 Fix experimental structure filtering
23e5762 Allow loading all experimental PDB xrefs
8a43305 Show PDB xref evidence separately from loaded structures
66569ec Add binder directness recompute command
b12b21c Add curated UniProt backfill and PDB coverage UI
9159db8 Allow LigQ to exclude problematic loci
e239d2a Load LigQ predicted ligands as ZINC
7aeb6b6 Import curated UniProt mappings
18afbd6 Add curated file pipeline UI action
99ba315 Show upload HTTP errors in UI
68b742f Store uploaded data files in shared datadir
4cf99dc Document large file transfer to Nodo0
4655ca4 Support multi-record GBK metadata sync
b51bd3d Show LigQ as pipeline stage 24
2b46654 Report LigQ excluded loci in curated plans
```

The exclusion-report code remains useful for true per-locus failures, but the
final Kp13 run did not use per-locus exclusions.

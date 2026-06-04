# Binders and LigQ_2 Operations

This document records how TargetPathogenWeb loads ligand/binder evidence from LigQ_2, how evidence is classified, and how to recover/reload results on Nodo0.

For the curated Klebsiella imports, final counts, the Kp13 LigQ_2/nodo3
diagnosis, and a reusable curated-file workflow, see
[`docs/KLEBSIELLA_CURATED_IMPORT.md`](KLEBSIELLA_CURATED_IMPORT.md).

## Evidence model

Binders are stored in `tpweb.models.Binders`.

Current binder categories:

| UI category | `source` | `is_direct` | Meaning |
|-------------|----------|-------------|---------|
| PDB direct | `pdb` | `True` | Ligand co-crystallized in a PDB structure for the same protein. Strongest evidence. |
| PDB homolog | `pdb` | `False` | Ligand co-crystallized in a PDB structure for a homolog/template protein. |
| ChEMBL direct | `chembl` | `True` | ChEMBL bioactivity hit for the same protein. |
| ChEMBL homolog | `chembl` | `False` | ChEMBL bioactivity hit inferred through a homolog/template protein. |
| ZINC | `proposed` | usually `False` | LigQ_2 proposed candidates. `is_direct` is not treated as primary evidence for this category. |

`is_direct=True` is computed by comparing:

- the `uniprot_id` reported by LigQ_2 for a binder/template row
- the protein's UniProt crossrefs in `BioentryDbxref` (`UnipSp` / `UnipTr`)

If they match, the binder is direct. If they do not match, the binder is via homolog.

This requires UniProt mapping to exist before loading LigQ_2 results.

## Required command pattern on Nodo0

Run Django management commands inside the web container with conda activated:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py <command>"
```

Cluster access path:

```bash
ssh agutson@cluster.qb.fcen.uba.ar
sudo su glyco
ssh nodo0
sudo su dockeradmin
cd ~/targetpathogenweb
```

## Deploying code changes

The source code is baked into the Docker image on Nodo0; only data directories are mounted. After `git pull`, rebuild the image:

```bash
git pull
make build ENV=cluster && make up ENV=cluster
```

For CSS/template-only changes, a container restart may be enough only if the image already contains the code. When in doubt, rebuild.

## Generate or refresh UniProt mapping

Run before loading binders for a genome:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py gbk2uniprot_map public__NC_002516.2 --batch_size 300 --datadir /app/targetpathogenweb/data"
```

The command first tries UniProt's async idmapping API. If that backend returns an error, TargetPathogenWeb falls back to UniProtKB search by RefSeq xref, e.g.:

```text
xref:RefSeq-NP_064721.1
```

Expected fallback progress looks like:

```text
UniProt mapping request failed for batch starting at 0: 400 Client Error ...
Using RefSeq xref fallback:  5%|...
```

The mapping is cached at:

```text
<genome_data_dir>/unips_mapping.csv
```

For PAO1:

```text
/data/targetpathogen/data/NC_/public__NC_002516.2/unips_mapping.csv
```

If a failed/empty mapping was cached, remove it and rerun:

```bash
sudo rm -f /data/targetpathogen/data/NC_/public__NC_002516.2/unips_mapping.csv
sudo rm -f /data/targetpathogen/data/NC_/public__NC_002516.2/unips_not_mapped.csv
rm -f not_mapped.lst
```

Verify mapping counts:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from bioseq.models.BioentryDbxref import BioentryDbxref
print('UnipSp:', BioentryDbxref.objects.filter(bioentry__biodatabase__name='public__NC_002516.2_prots', dbxref__dbname='UnipSp').count())
print('UnipTr:', BioentryDbxref.objects.filter(bioentry__biodatabase__name='public__NC_002516.2_prots', dbxref__dbname='UnipTr').count())
\""
```

In the PAO1 recovery run, the expected order of magnitude was:

```text
UnipSp: 1421
UnipTr: 4140
```

## Running LigQ_2 manually on cranex

Use this only when the automated remote pipeline is not being used.

LigQ_2 lives on cranex:

```text
/home/agutson/work/LigQ_2
```

Use the `search_backend` branch:

```bash
cd /home/agutson/work/LigQ_2
git checkout search_backend
```

FASTA files generated from the DB were copied to cranex:

```text
/home/agutson/tpw_ligq/NZ_AP023069/proteins.fasta
/home/agutson/tpw_ligq/NC_002516/proteins.fasta
```

SLURM script pattern:

```bash
cat > /home/agutson/tpw_ligq/run_NC_002516.sh << 'EOF'
#!/bin/bash
#SBATCH --job-name=ligq_NC_002516
#SBATCH --partition=cpu
#SBATCH --time=02:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8
#SBATCH --output=/home/agutson/tpw_ligq/NC_002516/slurm-%j.out

export PATH=/home/agutson/work/conda_envs/ligq_2_local/bin:$PATH

mkdir -p /home/agutson/tpw_ligq/NC_002516/output
cd /home/agutson/work/LigQ_2
python run_ligq_2.py \
    --input-fasta /home/agutson/tpw_ligq/NC_002516/proteins.fasta \
    --output-dir /home/agutson/tpw_ligq/NC_002516/output
EOF
sbatch /home/agutson/tpw_ligq/run_NC_002516.sh
```

Notes:

- Use the Python binary/environment directly by exporting `PATH`. This avoids compute-node conda activation issues.
- Do not use container-internal paths such as `/app/targetpathogenweb/data/...` on cranex. Copy FASTA files to cranex first.
- Check jobs with `squeue -u agutson`.
- Check output with `tail -30 /home/agutson/tpw_ligq/NC_002516/slurm-<jobid>.out`.

Expected success:

```text
Pipeline completed successfully.
Global summary shape: (5572, 10)
Results written under: /home/agutson/tpw_ligq/NC_002516/output
```

## Copy LigQ_2 output back to Nodo0

From Nodo0 as `dockeradmin`:

```bash
scp -r -i /home/dockeradmin/.ssh/id_ed25519_agutson_cluster \
    agutson@cluster.qb.fcen.uba.ar:/home/agutson/tpw_ligq/NC_002516/output/ \
    /data/targetpathogen/data/NC_/public__NC_002516.2/ligq2/
```

LigQ_2 `search_backend` writes `predicted_ligands.tsv`; the loader accepts it as
the ZINC/proposed-ligand table. Older `zinc_ligands.tsv` outputs are still
accepted.

## Load LigQ_2 results into the database

Dry-run first if the output is new:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py load_ligq_2_results --dry-run /app/targetpathogenweb/data/NC_/public__NC_002516.2/ligq2/output"
```

Delete existing binders for the proteome:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models.Binders import Binders
deleted, _ = Binders.objects.filter(locustag__biodatabase__name='public__NC_002516.2_prots').delete()
print(f'Deleted {deleted} binders')
\""
```

Load:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py load_ligq_2_results /app/targetpathogenweb/data/NC_/public__NC_002516.2/ligq2/output"
```

Typical PAO1 load summary:

```text
known: raw=51784  kept=40729  written=40729  missing_locustag=0
zinc:  raw=232379 kept=122852 written=122852 missing_locustag=0
```

## Verify direct vs homolog classification

After loading:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py shell -c \"
from tpweb.models.Binders import Binders
qs = Binders.objects.filter(locustag__biodatabase__name='public__NC_002516.2_prots')
print('total:', qs.count())
print('direct:', qs.filter(is_direct=True).count())
print('homolog:', qs.filter(is_direct=False).count())
print('pdb direct:', qs.filter(source='pdb', is_direct=True).count())
print('pdb homolog:', qs.filter(source='pdb', is_direct=False).count())
print('chembl direct:', qs.filter(source='chembl', is_direct=True).count())
print('chembl homolog:', qs.filter(source='chembl', is_direct=False).count())
print('zinc:', qs.filter(source='proposed').count())
\""
```

If `direct` is zero for a well-studied genome like PAO1, check UniProt mapping first. For less-studied genomes, all binders may legitimately be homolog-derived.

If UniProt mappings were imported after `load_ligq_2_results`, recompute the
direct/homolog flags without reloading LigQ output:

```bash
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py recompute_binder_directness public__NC_002516.2 --dry-run"
docker exec target2_nodo0_web bash -c ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && python manage.py recompute_binder_directness public__NC_002516.2"
```

## UI expectations

Genome overview:

- Highlights total binder evidence and shows a 5-category breakdown.
- PDB direct is the strongest evidence and should be interpreted separately from PDB homolog.

Protein detail:

- Binder list is table-based, not image-card based.
- Tabs: PDB direct, PDB homolog, ChEMBL direct, ChEMBL homolog, ZINC.
- Binder images are shown only on the binder detail page.

Binder detail:

- Shows a `Direct hit` or `Via homolog` badge based on `is_direct`.

## Common issues

### `gbk2uniprot_map` immediately reports all ids not found

Likely an empty `unips_mapping.csv` from a previous failed run is being reused. Remove it with `sudo rm` and rerun.

### UniProt async idmapping returns HTTP 400

This can be an upstream UniProt/EBI backend issue. The tpweb override falls back to UniProtKB search by RefSeq xref. Confirm the image contains the latest code and was rebuilt after pulling.

### No direct binders after reloading

Check:

1. `UnipSp` / `UnipTr` counts for that genome.
2. The genome name uses `_prots`, not `_prot`.
3. `recompute_binder_directness <genome>` has been run after UniProt mapping.
4. The genome may genuinely have no PDB/ChEMBL direct evidence.

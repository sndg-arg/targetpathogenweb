# Curated File Import Automation

This document describes the assisted import flow for genomes that already have
reviewed external result files, such as a `results_table.tsv`, a curated archive
with genome/structures/offtarget/essentiality folders, and optional LigQ_2
outputs.

The goal is not to replace the full TPW pipeline. The goal is to make curated
imports reproducible, safer, and easier to audit: load evidence that already
exists, preserve curated values, and generate an explicit plan for any remaining
heavy work.

## Scope

The current implementation is a staff/admin flow with CLI orchestration and persistent UI jobs.

It supports:

- validating a reviewed TSV with a required `gene` column;
- checking compatibility between TSV locus tags and the loaded TPW genome;
- inspecting a server-side `.tar`, `.tar.gz`, or compatible tar archive;
- detecting common archive folders such as `genome`, `structures`, `offtarget`,
  `essentiality`, `ligq2`, `LigQ_2`, and `ligq_2`;
- loading curated scores, UniProt mapping, and curated structures through the
  existing `import_external_results` command;
- optionally loading existing LigQ_2 binders;
- running UniProt and experimental PDB backfill through existing commands;
- printing a final audit and safe resume command;
- saving each UI validation/run as a `CuratedImportJob` with status, command, logs, report path, and retry metadata.

It does not yet create a new genome from scratch. In the current UI flow, the
base genome must already be loaded in TPW before the curated import panel can
validate protein overlap and run the curated flow.

## Safety Model

The command is conservative by default.

- `run_curated_file_import` runs as a dry-run unless `--execute` is passed.
- Archive extraction writes only into the genome-scoped
  `curated_import/extracted` workspace.
- Existing extraction files are not replaced unless `--overwrite-extract` is
  passed.
- Score replacement is controlled separately with `--overwrite-scores`.
- Heavy stages are not executed on nodo0 by this command. Remaining heavy work is
  reported as SLURM-required stages and represented as a safe resume command.
- Curated druggability remains the source of truth for the main Druggability
  score.

## Command

Dry-run example:

    /opt/conda/envs/tpv2/bin/python manage.py run_curated_file_import \
      --genome public__Example \
      --display-name Example \
      --gram n \
      --results-tsv /app/imports/Example/results_table.tsv \
      --archive /app/imports/Example/Example.tar.gz \
      --archive-root Example \
      --datadir /app/targetpathogenweb/data

Execution example:

    /opt/conda/envs/tpv2/bin/python manage.py run_curated_file_import \
      --genome public__Example \
      --display-name Example \
      --gram n \
      --results-tsv /app/imports/Example/results_table.tsv \
      --archive /app/imports/Example/Example.tar.gz \
      --archive-root Example \
      --datadir /app/targetpathogenweb/data \
      --execute \
      --extract \
      --overwrite-scores

If the archive is already extracted, pass the extracted paths instead:

    /opt/conda/envs/tpv2/bin/python manage.py run_curated_file_import \
      --genome public__Example \
      --results-tsv /app/imports/Example/results_table.tsv \
      --structures-dir /app/imports/Example/structures \
      --ligq-output-dir /app/imports/Example/ligq2/output \
      --datadir /app/targetpathogenweb/data \
      --execute \
      --overwrite-scores

Useful options:

- `--report PATH`: write the validation/execution report to a file.
- `--skip-uniprot-backfill`: skip UniProt GO/EC/PDB metadata backfill.
- `--skip-experimental-fetch`: skip experimental PDB structure fetch/load.
- `--skip-ligq`: skip LigQ_2 binder loading.
- `--overwrite-extract`: replace files only inside the curated extraction
  workspace.

## UI Flow

The upload page has a staff-only **Curated external import** panel.

Recommended use:

1. Upload TSV/archive through the **Upload a data file** panel.
2. Copy the returned server paths into **Curated external import**.
3. Fill in the TPW genome name, reviewed TSV path, optional extracted structures
   directory, optional archive path/root, optional LigQ_2 output directory, and
   TPW data directory.
4. Click **Validate import** first.
5. Review TSV rows/columns, matched proteins, unmatched TSV genes, structures
   status, archive root/folders/GBK candidates/LigQ-like files, and LigQ output
   status.
6. Click **Run curated flow** only after the validation looks correct.

The UI calls the same orchestration command used by CLI, so the command shown in
the panel can be copied and rerun from the shell for reproducibility.

## Persistent Job Tracking

The staff UI stores validations and curated-flow executions as `CuratedImportJob` records. Each job keeps the genome name, input paths, equivalent command, validation summary, stdout/stderr, generated report path, report text, status, phase, timestamps, and error message.

A failed curated-flow job can be retried from the same Upload Genome panel. Retry uses the stored parameters and writes a fresh report for the same job. Archive extraction during UI execution is confined to the genome-scoped curated import workspace and allows overwrite only inside that workspace so failed partial extracts can be retried without touching unrelated genome data.

## Done Criteria

A curated import is considered closed when the final report shows:

- the expected proteins are present in TPW;
- curated scores were imported;
- curated structure sources are loaded or explicitly absent;
- UniProt/GO/EC/PDB evidence was backfilled or intentionally skipped;
- existing LigQ evidence was loaded or intentionally skipped;
- remaining heavy stages are listed explicitly as SLURM work, or no heavy stages
  remain.

For complete closure, run the relevant source/pocket audit commands for the
organism and keep the final report under the genome data directory.

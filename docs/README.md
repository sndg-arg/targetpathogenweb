# Target Pathogen Web Documentation

Start here when you need to operate, import, debug, or explain Target. The docs are
written as reusable runbooks: keep organism-specific paths, job ids, counts, and
raw command output in tickets or task notes, not in these files.

## Choose The Right Guide

| Need | Read |
|------|------|
| Deploy or operate Nodo0 | [`CLUSTER_DEPLOY.md`](CLUSTER_DEPLOY.md) |
| Load a reviewed genome package by hand | [`CURATED_GENOME_IMPORT.md`](CURATED_GENOME_IMPORT.md) |
| Understand the curated import UI/staff flow | [`CURATED_FILE_IMPORT_AUTOMATION.md`](CURATED_FILE_IMPORT_AUTOMATION.md) |
| Load or repair LigQ_2 ligand evidence | [`BINDERS_LIGQ2.md`](BINDERS_LIGQ2.md) |
| Explain where Target data comes from | [`DATA_SOURCES.md`](DATA_SOURCES.md) |
| Check production health/logging expectations | [`OBSERVABILITY.md`](OBSERVABILITY.md) |
| Understand code structure and refactor direction | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Apply engineering/test quality rules | [`ENGINEERING_QUALITY.md`](ENGINEERING_QUALITY.md) |
| Apply UI color rules | [`COLOR_SYSTEM.md`](COLOR_SYSTEM.md) |

## Operating Principles

- **Curators first.** If a reviewed package contains a value, structure, pocket,
  binder, or annotation output, import that source. Do not recalculate it unless
  the reviewed file is absent or a rebuild was explicitly requested.
- **Nodo0 orchestrates; compute nodes compute.** Nodo0 is for Docker, database
  imports, file staging, small audits, and remote job monitoring. Full-proteome
  BLAST/HMMER, InterProScan, AlphaFold DB/ColabFold, FPocket, P2Rank, and LigQ_2 ligand evidence
  belong on SLURM compute nodes.
- **Dry-run before replacement.** Any import that overwrites scores, structures,
  pockets, or binders must have a dry-run or equivalent inspection first.
- **Validate closure.** A run is not done until the relevant audit command passes
  and the remaining missing files are either explained by the reviewed package or
  recorded as follow-up work.
- **Clean staging, not source.** Delete duplicate archives and logs only after
  confirming extraction/import. Never delete extracted reviewed source folders,
  TSVs, database volumes, or `/data/targetpathogen` wholesale.

## Documentation Standards

- Use placeholders such as `<GENOME>`, `<ARCHIVE_ROOT>`, `<PREFIX>`, and
  `<REMOTE_JOB_DIR>` in reusable docs.
- Avoid hardcoded run counts, job ids, timestamps, temporary paths, and organism
  names unless the document is explicitly a case note.
- Keep commands copyable. Include the container path when a host path differs
  from the path used by Django management commands.
- Prefer short checklists and explicit stop conditions over narrative history.
- When a one-off incident teaches something useful, write the generic rule here
  and keep the raw evidence in the ticket.

## Minimal Curated Import Checklist

1. Confirm reviewed TSV/archive source and expected genome name.
2. Copy large archives to Nodo0 with `scp`, not the web upload panel.
3. Extract reviewed files under `/data/targetpathogen/data/uploads/`.
4. Run `import_external_results --dry-run`, then execute if clean.
5. For Gates-style pockets, run `import_gates_pocket_outputs --dry-run`, then
   execute with `--force` only for the first replacement import.
6. Resume interrupted pocket imports without `--force`.
7. Run the relevant validation/audit commands.
8. Remove disposable duplicate archives/logs only after confirming source folders
   and imports are intact.

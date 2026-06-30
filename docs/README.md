# Documentation Index

Use this index to choose the right operational guide. Keep reusable docs generic:
put organism-specific paths, run outputs, and quantities in task notes or tickets.

## Operations

- [`CLUSTER_DEPLOY.md`](CLUSTER_DEPLOY.md): Nodo0 access, deployment, safe file transfer, and cluster operating rules.
- [`CURATED_GENOME_IMPORT.md`](CURATED_GENOME_IMPORT.md): manual curator-first import workflow for any reviewed genome package.
- [`CURATED_FILE_IMPORT_AUTOMATION.md`](CURATED_FILE_IMPORT_AUTOMATION.md): staff/UI automation for curated external imports.
- [`BINDERS_LIGQ2.md`](BINDERS_LIGQ2.md): LigQ_2 binder evidence loading and direct-vs-homolog checks.
- [`OBSERVABILITY.md`](OBSERVABILITY.md): health endpoints and request timing.

## Product and Engineering

- [`DATA_SOURCES.md`](DATA_SOURCES.md): user-facing explanation of TPW data provenance.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): current structure, target architecture, and refactor roadmap.
- [`ENGINEERING_QUALITY.md`](ENGINEERING_QUALITY.md): tests, tooling, and PR quality gate.
- [`COLOR_SYSTEM.md`](COLOR_SYSTEM.md): UI color tokens and visual rules.

## Documentation Rules

- Prefer source-of-truth workflows over one-off incident notes.
- Avoid hardcoding run counts, job ids, or temporary file paths in reusable docs.
- Use placeholders such as `<GENOME>`, `<ARCHIVE_ROOT>`, and `<REMOTE_JOB_DIR>`.
- When a one-off issue matters, record the lesson as a generic rule and keep the raw evidence in the task note.

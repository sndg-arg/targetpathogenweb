# Architecture Guide

## Current structure

- `tpweb/views/*`: request orchestration, rendering and API responses.
- `tpweb/services/*`: domain and transformation logic.
- `tpweb/services/pipeline_status.py`: runtime pipeline introspection from Parsl logs/process state.
- `tpweb/templates/*` + `static/css/pages/*`: UI composition and per-view stylesheets.

## Target architecture

- View layer:
  - Only parse request inputs and return response payloads/templates.
  - Avoid heavy business logic and repeated query/filter code.
- Service layer:
  - Hold business rules and reusable data transformations.
  - Keep functions pure where possible for easier testing.
- Integration layer:
  - Isolate external systems (Parsl filesystem/process checks, NCBI, tools) behind adapters.

## Engineering rules

- New reusable logic goes into `tpweb/services/*`, not directly in views.
- Any non-trivial pipeline/parsing logic must include unit tests.
- Keep functions small and explicit; avoid magic constants in views/templates.
- Prefer typed function signatures for new service modules.

## Refactor roadmap (phased)

1. Split `ProteinListView` orchestration into smaller query/filter services.
2. Add adapter module for command execution and filesystem reads (pipeline state).
3. Add contract tests for service layer and smoke tests for key routes.
4. Keep extracting inline CSS into `static/css/pages` and shared UI components.

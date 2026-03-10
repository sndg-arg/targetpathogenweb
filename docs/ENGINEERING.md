# Engineering Guide

This document merges architecture boundaries with quality and QA standards.

## 1. Architecture Boundaries

### Views (`tpweb/views/*`)

- Parse request inputs
- Orchestrate service calls
- Return HTTP responses/templates

Views should not carry heavy business logic.

### Services (`tpweb/services/*`)

- Hold reusable domain logic and transformations
- Keep data logic out of views whenever possible

### Integrations

- Pipeline status and filesystem/process checks should live in dedicated modules
- Example: `tpweb/services/pipeline_status.py`

### UI structure

- Templates: `tpweb/templates/*`
- Shared styles: `static/css/components/*`
- Page styles: `static/css/pages/*`

## 2. Design Rules

- Keep functions small and explicit
- Prefer pure transformation functions for testability
- Avoid magic constants in views/templates/JS
- New reusable behavior goes to `tpweb/services/*`

## 3. Tooling Baseline

- Lint/format: `ruff` (`pyproject.toml`)
- Git hooks: `.pre-commit-config.yaml`
- Test runner: `scripts/run_tests.py`
- Local shortcuts: `Makefile`
- CI: `.github/workflows/qa.yml`

## 4. Recommended Command Flow

Fast host checks:

```bash
make lint
make format
```

Stable container checks (recommended):

```bash
docker compose up -d db web
docker compose exec web make test
docker compose exec web make qa
```

Rationale: project DB host is `db`; container execution avoids local host mismatch.

## 5. Testing Strategy

- Unit/service tests:
  - business logic in `tpweb/services/*`
  - pipeline status parsing
- HTTP behavior tests:
  - health endpoints
  - critical template routes
  - key query/filter flows
- UI smoke checks:
  - `index`, `genomes`, `proteins`, `protein detail`
  - pagination/search behavior
  - 3D controls and modals

## 6. PR Quality Gate

A PR is ready when:

1. `make qa` passes (preferably inside `web`)
2. New behavior has tests or explicit justification
3. Business rules are not duplicated between views and services
4. No hardcoded hex colors in templates/styles
5. No unexplained magic values in new JS
6. CSS is in shared/page stylesheets, not inline blocks

## 7. Commit Discipline

- Keep commits focused by concern:
  - backend logic
  - UI/style
  - docs
  - pipeline operations
- Avoid mixing unrelated concerns in one commit
- For risky pipeline changes, include rollback notes in PR description

## 8. Related

- Root entrypoint: [../README.md](../README.md)
- Runtime and operations: [./OPERATIONS.md](./OPERATIONS.md)
- Frontend/UI guide: [./FRONTEND_UI.md](./FRONTEND_UI.md)

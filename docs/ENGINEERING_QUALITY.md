# Engineering Quality

## Tooling baseline

- Lint/format: `ruff` configured in `pyproject.toml`.
- Git hooks: `.pre-commit-config.yaml`.
- Test runner: `scripts/run_tests.py`.
- Developer shortcuts: `Makefile`.
- CI workflow: `.github/workflows/qa.yml`.

## Commands

```bash
pip install -r requirements/dev.txt
make lint
make format
make test
make qa
```

## Testing strategy

- Unit tests: service functions and pipeline status parsing.
- HTTP behavior tests: health endpoints, template routes, key query flows.
- Pipeline regression tests:
  - Stage mapping (`app` -> stage id/label).
  - Running genome detection from logs/process command line.
- UI checks:
  - Fast smoke checks for `index`, `genomes`, `proteins`.

## PR quality gate

- `make qa` must pass locally.
- New behavior must include tests.
- No new hardcoded color hexes in templates; use semantic tokens.
- No duplicated business logic between views and services.
- Page-level CSS should live in `static/css/pages/*` instead of inline `<style>` blocks.

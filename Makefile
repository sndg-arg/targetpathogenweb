PYTHON ?= python3

.PHONY: format lint test qa precommit-install precommit-run

format:
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) scripts/run_tests.py

qa: lint test

precommit-install:
	$(PYTHON) -m pre_commit install

precommit-run:
	$(PYTHON) -m pre_commit run --all-files

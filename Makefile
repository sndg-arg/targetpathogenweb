PYTHON ?= python3

# --- Docker Compose ---
# Local:   make up
# Cluster: make up ENV=cluster
# Service-scoped deploy: make build ENV=cluster svc=web && make up ENV=cluster svc=web
ENV ?= local
COMPOSE_ENV_FILES = $(if $(wildcard .env),--env-file .env) $(if $(wildcard .env.openai),--env-file .env.openai)
ifeq ($(ENV),cluster)
  COMPOSE = docker compose $(COMPOSE_ENV_FILES) -f docker-compose.yml -f docker-compose.cluster.yml
  CONTAINER_PYTHON = /opt/conda/envs/tpv2/bin/python
else
  COMPOSE = docker compose $(COMPOSE_ENV_FILES)
  CONTAINER_PYTHON = python
endif

.PHONY: build up down stop restart logs status migrate shell \
        format lint test qa precommit-install precommit-run

build:
	$(COMPOSE) build $(svc)

up:
	$(COMPOSE) up -d $(svc)

down:
	@echo "⚠️  Esto NO borra volúmenes. Para detener sin riesgo de perder datos."
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart $(svc)

logs:
	$(COMPOSE) logs --tail=50 -f $(svc)

status:
	$(COMPOSE) ps
	docker volume ls | grep targetpathogen

migrate:
	$(COMPOSE) exec web $(CONTAINER_PYTHON) manage.py migrate

shell:
	$(COMPOSE) exec web $(CONTAINER_PYTHON) manage.py shell



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

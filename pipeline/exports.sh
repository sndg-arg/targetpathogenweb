#!/bin/bash
export DJANGO_DEBUG=True
export DJANGO_SETTINGS_MODULE=tpwebconfig.settings
export DJANGO_DATABASE_URL=postgres://postgres:123@db:5432/tp?sslmode=disable
export CELERY_BROKER_URL=redis://localhost:6379/0
# Prepend project root so local command overrides can shadow site-packages when needed.
export PYTHONPATH=/app/targetpathogenweb:${PYTHONPATH}:../../sndgjobs:../../sndgbiodb:../../targetpathogen:../../sndg-bio:../../targetpathogenweb:../../targetpathogenweb/pipeline

# Execution profile:
#   cluster (default): keep strict/original behavior as much as possible
#   local: only enable deterministic local-safe tweaks by default
export TPW_PROFILE=${TPW_PROFILE:-cluster}

# Strict defaults for every profile unless explicitly overridden.
export TPW_REUSE_UNIPROT_MAP=${TPW_REUSE_UNIPROT_MAP:-0}
export TPW_FASTTARGET_ALLOW_FALLBACK=${TPW_FASTTARGET_ALLOW_FALLBACK:-0}
export FASTTARGET_TIMEOUT_SEC=${FASTTARGET_TIMEOUT_SEC:-0}

# Always use the cleaned genome indexing command. The original command is not
# robust against fuzzy GFF bounds (<,>) and breaks valid user uploads.
export TPW_USE_INDEX_GENOME_SEQ_CLEAN=1

#!/bin/bash
export DJANGO_DEBUG=True
export DJANGO_SETTINGS_MODULE=tpwebconfig.settings
export DJANGO_DATABASE_URL=DJANGO_DATABASE_URL=postgres://postgres:123@db:5432/tp?sslmode=disable
export CELERY_BROKER_URL=redis://localhost:6379/0
export PYTHONPATH=$PYTHONPATH:../../sndgjobs:../../sndgbiodb:../../targetpathogen:../../sndg-bio:../../targetpathogenweb:../../targetpathogenweb/parsl

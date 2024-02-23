#!/bin/bash
export DJANGO_DEBUG=True
export DJANGO_SETTINGS_MODULE=tpwebconfig.settings
export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp
export CELERY_BROKER_URL=redis://localhost:6379/0
export PYTHONPATH=$PYTHONPATH:../sndgjobs:../sndgbiodb:../targetpathogen:../sndg-bio:../targetpathogen

#Falta Biopython

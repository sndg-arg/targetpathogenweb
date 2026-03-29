#!/bin/sh
# Activate Conda environment
. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

# Run Django migrations
python manage.py migrate

# Start server — gunicorn for cluster, runserver for local dev
if [ "$TPW_PROFILE" = "cluster" ]; then
    python manage.py collectstatic --noinput
    gunicorn tpwebconfig.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
else
    python manage.py runserver 0.0.0.0:8000
fi

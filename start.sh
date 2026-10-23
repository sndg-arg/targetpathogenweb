#!/bin/sh
# Activate Conda environment
. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

# Run Django migrations
python manage.py migrate

# Start server — gunicorn for cluster, runserver for local dev
if [ "$TPW_PROFILE" = "cluster" ]; then
    python manage.py collectstatic --noinput
    # gthread: with plain sync workers, 3 slow protein pages (10-40 s each) at
    # once blocked every other request. Override via env if needed.
    # Page requests only: a query still running when gunicorn gives up on the
    # request (120 s) is cancelled by Postgres instead of running on and
    # slowing every other page. Migrations above and `docker exec` commands
    # don't inherit it.
    DJANGO_STATEMENT_TIMEOUT_MS="${DJANGO_STATEMENT_TIMEOUT_MS:-115000}"     gunicorn tpwebconfig.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --worker-class gthread --threads "${GUNICORN_THREADS:-4}" --timeout 120
else
    python manage.py runserver 0.0.0.0:8000
fi

#!/bin/sh
# Activate Conda environment
. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

# Run Django migrations
python manage.py migrate

# Start Django development server
python manage.py runserver 0.0.0.0:8000


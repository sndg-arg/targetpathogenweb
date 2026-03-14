#!/bin/sh
. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

QUEUE_POLL_INTERVAL="${QUEUE_POLL_INTERVAL:-5}"

python manage.py tpweb_process_genome_queue --poll-interval "${QUEUE_POLL_INTERVAL}"

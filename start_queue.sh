#!/bin/sh
# Allow appuser to use the Docker socket (needed for TP.psort → docker run psortb)
if [ -S /var/run/docker.sock ]; then
  chmod 666 /var/run/docker.sock 2>/dev/null || true
fi

. /opt/conda/etc/profile.d/conda.sh
conda activate tpv2

if [ -f ./parsl/exports.sh ]; then
  . ./parsl/exports.sh
fi

QUEUE_POLL_INTERVAL="${QUEUE_POLL_INTERVAL:-5}"

exec python manage.py tpweb_process_genome_queue --poll-interval "${QUEUE_POLL_INTERVAL}"

#!/usr/bin/env bash
# Explicit, bounded exception for the current recovery; remote defaults stay enabled.
# TPW_ALLOW_NODO0_PSORT=1 bash scripts/cluster/recover_psort_nodo0.sh public__ACCESSION n
set -euo pipefail
if [ "${TPW_ALLOW_NODO0_PSORT:-0}" != 1 ]; then
  echo "This recovery runs PSORT on nodo0. Set TPW_ALLOW_NODO0_PSORT=1 for an authorized exception." >&2
  exit 1
fi
genome="${1:?Usage: recover_psort_nodo0.sh INTERNAL_ACCESSION [n|p]}"
gram="${2:-n}"
if [[ "$genome" == *[!a-zA-Z0-9_.-]* ]] || [[ "$gram" != n && "$gram" != p ]]; then
  echo "Invalid genome identifier or Gram type" >&2
  exit 1
fi
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
queue="${TPW_RECOVERY_QUEUE_CONTAINER:-target2_nodo0_queue}"
bucket="${genome:$((${#genome}/2-1)):3}"
container_folder="/app/targetpathogenweb/data/$bucket/$genome"
work="$HOME/tpw_psort_recovery/$genome"
# Do not overlap two local recoveries, even for different genomes.
exec 9>"$HOME/.tpw-psort-nodo0.lock"
flock -n 9 || { echo "Another nodo0 PSORT recovery is active" >&2; exit 1; }
processes=$(docker exec "$queue" ps aux)
if printf '%s\n' "$processes" | grep -q '[r]un_pipeline_direct.py'; then
  echo "A pipeline is already running in $queue; wait before resuming." >&2
  exit 1
fi
mkdir -p "$work"
# Use the invoking user's workspace: the mounted genome directory can be root-owned.
docker exec "$queue" sh -c '
  if [ -s "$1" ]; then cat "$1"; else gzip -dc "$1.gz"; fi
' psort-recovery "$container_folder/$genome.faa" > "$work/input.faa"
echo "PSORT recovery: two workers, at most 2 CPU / 4 GiB total for PSORT containers."
python3 "$repo/pipeline/psort_worker.py" \
  --engine docker --runtime docker --image brinkmanlab/psortb_commandline:1.0.2 \
  --fasta "$work/input.faa" --output "$work/psort.tsv" \
  --cache "$work/cache" --gram "$gram" \
  --workers 2 --batch-size 50 --timeout 1800

candidate="$container_folder/.psort-recovery-$$.tsv"
docker cp "$work/psort.tsv" "$queue:$candidate"
docker exec "$queue" sh -c 'chmod 644 "$1" && mv "$1" "$2"' \
  psort-recovery "$candidate" "$container_folder/psort.tsv"

echo "Validated PSORT complete. Resuming stage 21, then remote LigQ (24)."
# 22/23 are explicitly omitted: LigQ loads binder evidence directly. This also
# works with the previous queue image, so recovery needs no container restart.
docker exec "$queue" bash -lc '
  set -e
  cd /app/targetpathogenweb/pipeline
  source exports.sh
  export TPW_LIGQ_USE_REMOTE=1
  source_accession=${1#*__}
  exec /opt/conda/envs/tpv2/bin/python -u run_pipeline_direct.py \
    "$source_accession" --genome-name "$1" --gram "$2" --start-stage 21 \
    --skip-stages 22,23 --no-local-heavy
' psort-recovery "$genome" "$gram"

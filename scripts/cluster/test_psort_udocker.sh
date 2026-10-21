#!/usr/bin/env bash
# From nodo0: bash scripts/cluster/test_psort_udocker.sh public__ACCESSION n CONTAINER
# Prepares 50 proteins, submits this script to SLURM, validates exact coverage.
#SBATCH --job-name=psort_test50
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=psort-udocker-prediction-%j.log
set -euo pipefail

if [ -z "${SLURM_JOB_ID:-}" ]; then
  genome="${1:?Usage: test_psort_udocker.sh INTERNAL_ACCESSION n|p UDOCKER_CONTAINER}"
  gram="${2:?Specify n or p}"
  container="${3:?Specify the container name from the successful udocker probe}"
  if [[ "$genome" == *[!a-zA-Z0-9_.-]* || "$container" == *[!a-zA-Z0-9_.-]* ]] ||
     [[ "$gram" != n && "$gram" != p ]]; then
    echo "Invalid genome, container name or Gram type" >&2
    exit 1
  fi
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
  queue="${TPW_RECOVERY_QUEUE_CONTAINER:-target2_nodo0_queue}"
  remote_dir="/home/agutson/tpw_psort_udocker_test/test_$(date +%Y%m%d_%H%M%S)_$$"
  bucket="${genome:$((${#genome}/2-1)):3}"
  ssh_command=(docker exec -i "$queue" ssh
    -F /tmp/fakehome/.ssh/config
    -i /tmp/fakehome/.ssh/id_ed25519_agutson_cluster
    agutson@cluster.qb.fcen.uba.ar)

  echo "Preparing 50 proteins in $remote_dir"
  "${ssh_command[@]}" "mkdir -p '$remote_dir'"
  docker exec "$queue" awk '/^>/{if (++n > 50) exit} {print}' \
    "/app/targetpathogenweb/data/$bucket/$genome/$genome.faa" |
    "${ssh_command[@]}" "cat > '$remote_dir/input.faa'"
  "${ssh_command[@]}" "cat > '$remote_dir/psort_worker.py'" < "$repo/pipeline/psort_worker.py"
  job=$("${ssh_command[@]}" \
    "test -s '$remote_dir/input.faa' && test -s '$remote_dir/psort_worker.py' && sbatch --parsable --export=ALL,TPW_PSORT_TEST_DIR=$remote_dir,TPW_PSORT_TEST_CONTAINER=$container,TPW_PSORT_TEST_GRAM=$gram" \
    < "$repo/scripts/cluster/test_psort_udocker.sh")
  job="${job%%;*}"
  if [[ ! "$job" =~ ^[0-9]+$ ]]; then
    echo "Submission did not return a valid SLURM ID: $job" >&2
    exit 1
  fi
  echo "Submitted PSORT prediction test: job $job"
  echo "Remote log: ~/psort-udocker-prediction-$job.log"
  exit 0
fi

base="${TPW_PSORT_TEST_DIR:?Missing test directory}"
container="${TPW_PSORT_TEST_CONTAINER:?Missing udocker container}"
gram="${TPW_PSORT_TEST_GRAM:?Missing Gram type}"
export UDOCKER_DIR="$HOME/tpw_psort_udocker"
cd "$base"
if [ "$(grep -c '^>' input.faa)" -ne 50 ]; then
  echo "Test requires exactly 50 input proteins" >&2
  exit 1
fi
mkdir -p results
"$HOME/work/venvs/tpw_udocker/bin/udocker" run \
  -v "$base:/tmp" --entrypoint=/usr/local/psortb/bin/psort \
  "$container" "-$gram" -o terse -i /tmp/input.faa

"$HOME/.conda/envs/fasttarget/bin/python" - <<'PY'
from pathlib import Path
from psort_worker import read_fasta, read_predictions, write_predictions

records = read_fasta("input.faa")
if len(records) != 50:
    raise RuntimeError(f"Expected 50 proteins, found {len(records)}")
files = list(Path("results").glob("*_psortb_*.txt"))
if len(files) != 1:
    raise RuntimeError(f"Expected one raw PSORT output, found {len(files)}")
rows = read_predictions(files[0], {name for name, _ in records})
write_predictions("psort.tsv", rows, records)
print(f"PREDICTION TEST OK: {len(rows)}/50 predictions validated")
PY

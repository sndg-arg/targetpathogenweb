#!/usr/bin/env bash
# Submit on a compute node: sbatch scripts/cluster/setup_psort_udocker.sh
#SBATCH --job-name=tpw_psort_udocker_setup
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --output=psort-udocker-setup-%j.log
set -euo pipefail
if [ -z "${SLURM_JOB_ID:-}" ] || [ "$(id -u)" -eq 0 ]; then
  echo "Run this setup via sbatch as an unprivileged cluster user." >&2
  exit 1
fi
python_bin="${TPW_PSORT_PROBE_PYTHON:-$HOME/.conda/envs/fasttarget/bin/python}"
venv="$HOME/work/venvs/tpw_udocker"
if [ ! -x "$venv/bin/python" ]; then
  "$python_bin" -m venv "$venv"
fi
"$venv/bin/python" -m pip install 'udocker==1.3.17'
export UDOCKER_DIR="${TPW_PSORT_UDOCKER_DIR:-$HOME/tpw_psort_udocker}"
runtime="${TPW_PSORT_UDOCKER_BIN:-$venv/bin/udocker}"
image="${TPW_PSORT_IMAGE:-brinkmanlab/psortb_commandline:1.0.2}"
"$runtime" install
if ! "$runtime" --quiet inspect "$image" >/dev/null 2>&1; then
  "$runtime" pull "$image"
fi
"$runtime" --quiet inspect "$image" >/dev/null
container="tpw_psort_setup_${SLURM_JOB_ID}"
created=0
cleanup() {
  if [ "$created" = 1 ]; then
    "$runtime" --quiet rm "$container"
  fi
}
trap cleanup EXIT
"$runtime" --quiet create --name="$container" "$image"
created=1
"$runtime" --quiet setup --execmode=P1 "$container"
"$runtime" --quiet run --entrypoint=/usr/local/psortb/bin/psort "$container" --version
echo "PSORT udocker setup OK: runtime=$runtime image=$image"

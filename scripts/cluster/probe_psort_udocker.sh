#!/usr/bin/env bash
# Optional SLURM probe for a PRoot-based alternative to Apptainer.
# This only tests runtime/tool startup; it does not process or modify a genome.
#SBATCH --job-name=tpw_psort_udocker_probe
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --output=psort-udocker-probe-%j.log
set -euo pipefail
if [ -z "${SLURM_JOB_ID:-}" ] || [ "$(id -u)" -eq 0 ]; then
  echo "Run this probe via sbatch as an unprivileged cluster user." >&2
  exit 1
fi
python_bin="${TPW_PSORT_PROBE_PYTHON:-$HOME/.conda/envs/fasttarget/bin/python}"
venv="$HOME/work/venvs/tpw_udocker"
if [ ! -x "$venv/bin/python" ]; then
  "$python_bin" -m venv "$venv"
fi
"$venv/bin/python" -m pip install 'udocker==1.3.17'
export UDOCKER_DIR="$HOME/tpw_psort_udocker"
udocker="$venv/bin/udocker"
"$udocker" install
"$udocker" pull brinkmanlab/psortb_commandline:1.0.2
container="tpw_psort_probe_${SLURM_JOB_ID}"
"$udocker" create --name="$container" brinkmanlab/psortb_commandline:1.0.2
"$udocker" setup --execmode=P1 "$container"
"$udocker" run --entrypoint=/usr/local/psortb/bin/psort "$container" --version
"$udocker" run --entrypoint=/usr/bin/perl "$container" \
  -MBio::Tools::Run::SCLBlast -e 'print "SCLBlast module loaded\n";'
echo "UDOCKER PROBE OK: tool startup works; genome execution is not yet validated."

#!/usr/bin/env bash
# Submit on the cluster: sbatch scripts/cluster/setup_psort.sh
#SBATCH --job-name=tpw_psort_setup
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --output=psort-setup-%j.log

set -eo pipefail
if [ -z "${SLURM_JOB_ID:-}" ]; then
  echo "Run this setup via sbatch on a compute node." >&2
  exit 1
fi
prefix="$HOME/work/conda_envs/tpw_apptainer"
runtime="${TPW_PSORT_APPTAINER_BIN:-$prefix/bin/apptainer}"
image="${TPW_PSORT_IMAGE:-$HOME/tpw_images/psortb_1.0.2.sif}"
if ! command -v "$runtime" >/dev/null 2>&1; then
  if [ "$runtime" != "$prefix/bin/apptainer" ]; then
    echo "Configured Apptainer executable does not exist: $runtime" >&2
    exit 1
  fi
  unshare -Ur true || {
    echo "Unprivileged user namespaces are unavailable. Ask the cluster administrator for a supported Apptainer installation." >&2
    exit 1
  }
  source "${TPW_PSORT_CONDA_ROOT:-/home/shared/miniconda3.8}/etc/profile.d/conda.sh"
  export CONDA_PKGS_DIRS="$HOME/.conda/pkgs"
  mkdir -p "$CONDA_PKGS_DIRS"
  conda create -y -p "$prefix" \
    --override-channels -c conda-forge python=3.10 apptainer
fi
set -u
mkdir -p "$(dirname "$image")"
if [ ! -s "$image" ]; then
  "$runtime" pull "$image" docker://brinkmanlab/psortb_commandline:1.0.2
fi
"$runtime" exec --cleanenv --containall "$image" \
  /usr/local/psortb/bin/psort --version
echo "PSORT setup OK: runtime=$runtime image=$image"

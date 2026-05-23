#!/bin/bash
#SBATCH --job-name=ligq2
#SBATCH --cpus-per-task=8
#SBATCH --time=48:00:00
#SBATCH --mem=32G
#SBATCH -o slurm-ligq2-%j.out
#SBATCH -e slurm-ligq2-%j.err
#
# Usage:  sbatch ligq_batch.sbatch <input.fasta> <output_dir>
#
# Required env vars (with defaults):
#   LIGQ_DIR           default: /home/agutson/work/LigQ_2
#   LIGQ_CONDA_PREFIX  default: /home/shared/miniconda3.8
#   LIGQ_CONDA_ENV     default: ligq2
#   LIGQ_DATA_DIR      default: /home/agutson/work/ligq_data
#

set -euo pipefail

INPUT_FASTA="$1"
OUTPUT_DIR="$2"
LIGQ_DIR="${LIGQ_DIR:-/home/agutson/work/LigQ_2}"
LIGQ_CONDA_PREFIX="${LIGQ_CONDA_PREFIX:-/home/shared/miniconda3.8}"
LIGQ_CONDA_ENV="${LIGQ_CONDA_ENV:-ligq2}"
LIGQ_DATA_DIR="${LIGQ_DATA_DIR:-/home/agutson/work/ligq_data}"

mkdir -p "${OUTPUT_DIR}"

# shellcheck disable=SC1091
source "${LIGQ_CONDA_PREFIX}/etc/profile.d/conda.sh"
conda activate "${LIGQ_CONDA_ENV}"

WORKDIR="$(mktemp -d -p /tmp ligq2_run.XXXXXX)"
trap "rm -rf ${WORKDIR}" EXIT
cd "${WORKDIR}"
ln -s "${LIGQ_DATA_DIR}" databases

echo "[$(date)] starting LigQ_2"
echo "  INPUT:  ${INPUT_FASTA}"
echo "  OUTPUT: ${OUTPUT_DIR}"
echo "  WORK:   ${WORKDIR}"
echo "  DATA:   ${LIGQ_DATA_DIR}"
echo "  ENV:    ${LIGQ_CONDA_PREFIX}/envs/${LIGQ_CONDA_ENV}"

python "${LIGQ_DIR}/run_ligq_2.py" \
  --input-fasta "${INPUT_FASTA}" \
  --output-dir "${OUTPUT_DIR}"

echo "[$(date)] LigQ_2 finished. Output at: ${OUTPUT_DIR}"

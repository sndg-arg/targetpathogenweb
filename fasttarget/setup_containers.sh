#!/bin/bash

# Detect whether to use apptainer or singularity
if command -v apptainer &> /dev/null; then
    CONTAINER_CMD="apptainer"
    echo "Using apptainer for container management"
elif command -v singularity &> /dev/null; then
    CONTAINER_CMD="singularity"
    echo "Using singularity for container management"
else
    echo "ERROR: Neither apptainer nor singularity is installed"
    echo "Please install one of them:"
    echo "  - Apptainer: https://apptainer.org/docs/admin/main/installation.html"
    echo "  - Singularity: https://sylabs.io/guides/latest/user-guide/quick_start.html"
    exit 1
fi

# Create directory for container .sif files
mkdir -p singularity_sfi_files

# Pull containers with specific names matching what the code expects
echo "Pulling containers..."

$CONTAINER_CMD pull --name singularity_sfi_files/sangerpathogens_roary.sif docker://sangerpathogens/roary
$CONTAINER_CMD pull --name singularity_sfi_files/fpocket_fpocket.sif docker://fpocket/fpocket
$CONTAINER_CMD pull --name singularity_sfi_files/brinkmanlab_psortb_commandline_1.0.2.sif docker://brinkmanlab/psortb_commandline:1.0.2
$CONTAINER_CMD pull --name singularity_sfi_files/mcpalumbo_corecruncher_1.sif docker://mcpalumbo/corecruncher:1
$CONTAINER_CMD pull --name singularity_sfi_files/mcpalumbo_bioperl_1.sif docker://mcpalumbo/bioperl:1
$CONTAINER_CMD pull --name singularity_sfi_files/mcpalumbo_foldseek_1.sif docker://mcpalumbo/foldseek:1
$CONTAINER_CMD pull --name singularity_sfi_files/mcpalumbo_p2rank_latest.sif docker://mcpalumbo/p2rank:latest
$CONTAINER_CMD pull --name singularity_sfi_files/mcpalumbo_metagraphtools_latest.sif docker://mcpalumbo/metagraphtools:latest
$CONTAINER_CMD pull --name singularity_sfi_files/ghcr_executor-p2rank_main.sif docker://ghcr.io/cusbg/executor-p2rank:main

echo ""
echo "Containers have been pulled successfully to singularity_sfi_files/ using $CONTAINER_CMD"
echo ""
echo "To use with Nextflow, run with the appropriate profile:"
echo "  - For apptainer: nextflow run main.nf -profile apptainer ..."
echo "  - For singularity: nextflow run main.nf -profile singularity ..."

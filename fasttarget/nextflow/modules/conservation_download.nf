#!/usr/bin/env nextflow

/*
 * Module: Conservation - Download Genomes
 * ========================================
 * Downloads and prepares genomes from NCBI for conservation analysis
 * 
 * Steps:
 * 1. Download complete NCBI genomes from organism tax_id
 * 2. Download missing accessions
 * 3. Check and filter genomes (presence of .gff and .faa files)
 * 
 * Creates the dataset folder with all downloaded genomes
 */

process CONSERVATION_DOWNLOAD_GENOMES {
    tag "${organism_name}"
    label 'medium_resources'
    // Only publish downloaded datasets (genome files), keep gff/faa in work for next steps
    publishDir "${output_path}", mode: 'move', pattern: "${organism_name}/conservation/${organism_name}_dataset/"
    
    input:
    val organism_name
    val output_path
    val tax_id
    val container_engine
    path genome_files
    val accession_file
    
    output:
    path "${organism_name}/conservation/${organism_name}_dataset/", emit: dataset_dir
    path "${organism_name}/conservation/core_genomes_IDs.txt", emit: genome_ids
    path "${organism_name}/conservation/roary_output/gff/", emit: gff_dir
    path "${organism_name}/conservation/corecruncher_output/faa/", emit: faa_dir
    path "${organism_name}/conservation/*", emit: all_conservation
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    def accession_file_arg = accession_file.toString() != 'NO_FILE' ? accession_file.toString() : 'null'
    """#!/usr/bin/env python3

import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import genome

print('=' * 80)
print('CONSERVATION ANALYSIS - GENOME DOWNLOAD'.center(80))
print('=' * 80)

# Create conservation directory in work dir
work_dir = os.getcwd()
conservation_dir = os.path.join(work_dir, 'conservation')
os.makedirs(conservation_dir, exist_ok=True)

# Create genome directory structure and copy reference genome files
genome_work_dir = os.path.join(work_dir, '${organism_name}', 'genome')
os.makedirs(genome_work_dir, exist_ok=True)

# Copy genome files to expected location
import shutil
import glob
for f in glob.glob('*.gbk') + glob.glob('*.faa') + glob.glob('*.gff') + glob.glob('*.fna') + glob.glob('*.ffn'):
    shutil.copy(f, genome_work_dir)

# Read accession list if provided
accession_list = None
accession_file_path = '${accession_file_arg}'
if accession_file_path != 'null' and os.path.exists(accession_file_path):
    print(f'Reading accession list from: {accession_file_path}')
    with open(accession_file_path, 'r') as f:
        accession_list = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    print(f'Found {len(accession_list)} accessions to download')

print('')
if accession_list:
    print(f'[1] Downloading {len(accession_list)} specific genomes from accession list...')
else:
    print('[1] Downloading tax_id genomes from NCBI...')
genome.core_download_genomes_ncbi(work_dir, '${organism_name}', ${tax_id}, accession_list=accession_list)

print('')
print('[2] Downloading missing accessions...')
genome.core_download_missing_accessions(work_dir, '${organism_name}', ${tax_id}, accession_list=accession_list)

print('')
print('[3] Selecting and filtering genomes...')
genome.core_check_files(work_dir, '${organism_name}', container_engine='${container_engine}')

print('')
print('Genome download and preparation completed')
"""
    
    stub:
    """
    mkdir -p conservation/${organism_name}_dataset/ncbi_dataset/data
    touch conservation/core_genomes_IDs.txt
    echo "STUB: Genome download for ${organism_name}"
    """
}

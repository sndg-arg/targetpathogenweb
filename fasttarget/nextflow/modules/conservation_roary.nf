#!/usr/bin/env nextflow

/*
 * Module: Conservation - Roary Analysis
 * ======================================
 * Runs Roary pangenome analysis on downloaded genomes
 * 
 * Steps:
 * 1. Prepare GFF files in roary_output/gff/
 * 2. Run Roary with specified parameters
 * 3. Parse Roary output to generate core genes table
 * 
 * Can run in parallel with CoreCruncher
 */

process CONSERVATION_ROARY {
    tag "${organism_name}"
    label 'high_resources'
    publishDir "${output_path}", mode: 'move', pattern: "${organism_name}/conservation/**"
    
    input:
    val organism_name
    val output_path
    path gff_dir
    path genome_files
    val min_core_freq
    val min_identity
    val cpus
    val container_engine
    
    output:
    path "${organism_name}/conservation/core_roary.tsv", emit: core_table
    path "${organism_name}/conservation/roary_output/results/gene_presence_absence.csv", emit: gene_presence_absence
    path "${organism_name}/conservation/roary_output/", emit: roary_dir
    path "${organism_name}/conservation/**", emit: all_roary
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3

import sys
import os
import shutil
import glob


# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

import shutil
import glob
from ftscripts import genome
import shutil as shutil_module

print('=' * 80)
print('ROARY PANGENOME ANALYSIS'.center(80))
print('=' * 80)

# Setup work directory structure
work_dir = os.getcwd()
conservation_dir = os.path.join(work_dir, '${organism_name}', 'conservation')
roary_output_dir = os.path.join(conservation_dir, 'roary_output')
os.makedirs(roary_output_dir, exist_ok=True)  # Create parent, NOT gff subdir

print(f'Working in: {work_dir}')
print(f'Conservation directory: {conservation_dir}')
print(f'Roary output directory: {roary_output_dir}')

# Copy genome files to expected location
genome_dir = os.path.join(work_dir, '${organism_name}', 'genome')
os.makedirs(genome_dir, exist_ok=True)
for genome_file in glob.glob('${organism_name}.*'):
    target_file = os.path.join(genome_dir, os.path.basename(genome_file))
    shutil.copy2(genome_file, target_file)
    print(f'Copied genome file: {os.path.basename(genome_file)}')

# Link GFF files from upstream work directory (avoid duplication)
# gff_dir already exists from CONSERVATION_DOWNLOAD_GENOMES work/
staged_gff_dir = '${gff_dir}'
gff_target_dir = os.path.join(roary_output_dir, 'gff')

print(f'Creating symlinks to GFF files from: {staged_gff_dir}')
print(f'Target: {gff_target_dir}')
gff_files = glob.glob(os.path.join(staged_gff_dir, '*.gff'))

# Remove existing directory and symlink to upstream instead
if os.path.exists(gff_target_dir) and os.path.islink(gff_target_dir):
    os.unlink(gff_target_dir)
elif os.path.exists(gff_target_dir):
    shutil_module.rmtree(gff_target_dir)

try:
    os.symlink(staged_gff_dir, gff_target_dir)
    print(f'  - Symlinked entire gff directory: {staged_gff_dir}')
except OSError:
    # Fallback: copy if symlink fails
    shutil.copytree(staged_gff_dir, gff_target_dir, dirs_exist_ok=True)
    print(f'  - Copied gff directory (symlink failed)')

print(f'Total GFF files copied: {len(gff_files)}')
print('')
print(f'Parameters:')
print(f'  - Min core frequency: ${min_core_freq}%')
print(f'  - Min identity: ${min_identity}%')
print(f'  - CPUs: ${cpus}')

print('[1] Running Roary...')
print('')
genome.core_genome_programs(
    work_dir,
    '${organism_name}',
    ${min_core_freq},
    ${min_identity},
    ${cpus},
    program_list=['roary'],
    container_engine='${container_engine}'
)

print('[2] Parsing Roary results...')
print('')
df_roary = genome.roary_output(
    work_dir,
    '${organism_name}',
    core_threshold=${min_core_freq}/100
)

print(f'Roary analysis completed')
print('')
print(f'  - Core genes found: {len(df_roary)}')

# Verify Roary output file exists and has data
import pandas as pd
gene_presence_file = os.path.join(conservation_dir, 'roary_output/results/gene_presence_absence.csv')

if not os.path.exists(gene_presence_file):
    raise FileNotFoundError(f'Critical file not found: {gene_presence_file}')

if os.path.getsize(gene_presence_file) == 0:
    raise ValueError(f'Critical file is empty (0 bytes): {gene_presence_file}')

# Check that file has actual data rows, not just header
try:
    df_check = pd.read_csv(gene_presence_file)
    if len(df_check) == 0:
        raise ValueError(f'File has header but no data rows: {gene_presence_file}')
    print(f'  ✓ Verified: gene_presence_absence.csv has {len(df_check)} genes')
except pd.errors.EmptyDataError:
    raise ValueError(f'File is empty or corrupted: {gene_presence_file}')
"""
    
    stub:
    """
    # Create dummy directory structure for testing
    mkdir -p conservation/roary_output/gff
    mkdir -p conservation/roary_output/results
    
    # Create dummy files with actual content (not just empty) for validation
    echo -e "Gene,Non-unique Gene name,Annotation,No. isolates,No. sequences\\ngene1,test_gene,Test annotation,10,10" > conservation/roary_output/results/gene_presence_absence.csv
    echo -e "gene\\troary_core\\ngene1\\t1" > conservation/core_roary.tsv
    
    echo "STUB: Roary analysis for ${organism_name} (dummy files with data created for testing)"
    """
}

#!/usr/bin/env nextflow

/*
 * Module: Structures - Download
 * ==============================
 * Stage 2: Downloads PDB and AlphaFold structures in parallel
 * 
 * Steps:
 * 1. Create directory structure for each gene
 * 2. Generate structure summary tables
 * 3. Download PDB and AlphaFold structures (PARALLEL per gene)
 * 4. Extract reference structure chains
 * 
 * Uses scatter-gather pattern for efficient parallel downloads
 */

process STRUCTURES_PREPARE {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/structures/**"
    
    input:
    val organism_name
    val output_path
    path uniprot_dir
    path gbk
    val resolution_cutoff
    val coverage_cutoff

    output:
    path "${organism_name}/structures/", emit: structure_dir
    path "${organism_name}/structures/*/*_structure_summary.tsv", emit: locus_dirs, optional: true
    path "locus_tags.txt", emit: locus_tags_list
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent

    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures, metadata

# Print progress to stderr so stdout is clean for locus tags
print('=' * 80, file=sys.stderr)
print('STAGE 2A: STRUCTURE PREPARATION'.center(80), file=sys.stderr)
print('─' * 80, file=sys.stderr)

# Setup work directory
work_dir = os.getcwd()

# Create organism directory structure
structures_dir = os.path.join(work_dir, '${organism_name}', 'structures')
os.makedirs(structures_dir, exist_ok=True)

# Copy staged uniprot_files to expected location
import shutil
import glob
uniprot_source = '${uniprot_dir}'
uniprot_dest = os.path.join(structures_dir, 'uniprot_files')
if os.path.exists(uniprot_source):
    shutil.copytree(uniprot_source, uniprot_dest)

# Copy genome files to expected location
genome_dir = os.path.join(work_dir, '${organism_name}', 'genome')
gbk_path = '${gbk}'
os.makedirs(genome_dir, exist_ok=True)
target_file = os.path.join(genome_dir, os.path.basename(gbk_path))
shutil.copy2(gbk_path, target_file)
print(f'Copied genome file: {os.path.basename(gbk_path)}', file=sys.stderr)

print(f'Working in: {work_dir}', file=sys.stderr)

print('[2.1] Creating directory structure for each gene...', file=sys.stderr)
structures.create_subfolder_structures(work_dir, '${organism_name}')

print('[2.2] Generating structure summary tables...', file=sys.stderr)
structures.create_summary_structure_file(work_dir, '${organism_name}', resolution_cutoff=${resolution_cutoff}, coverage_cutoff=${coverage_cutoff})

# Output list of locus tags for parallel processing to a file
all_locus_tags = metadata.ref_gbk_locus(work_dir, '${organism_name}')
with open('locus_tags.txt', 'w') as f:
    for tag in all_locus_tags:
        f.write(tag + '\\n')

print(f'Generated locus_tags.txt with {len(all_locus_tags)} tags', file=sys.stderr)
print('Stage 2A completed - Ready for parallel downloads', file=sys.stderr)
"""
    
    stub:
    """
    mkdir -p structures/gene_example
    touch structures/gene_example/gene_example_structure_summary.tsv
    echo "gene_example"
    echo "STUB: Structure preparation for ${organism_name}" >&2
    """
}

process STRUCTURES_DOWNLOAD_SINGLE {
    tag "${locus_tag}"
    label 'low_resources'
    maxForks 10  // Download up to 10 genes in parallel
    
    errorStrategy 'retry'
    maxRetries 3
    
    input:
    tuple val(locus_tag), path(structure_dir)
    
    output:
    val locus_tag, emit: completed_tag
    path "downloads/${locus_tag}", emit: locus_structures, optional: true
    tuple val(locus_tag), path("downloads/${locus_tag}"), emit: locus_download_pair, optional: true
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3

import sys
import os
import shutil
import csv

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures

# Create local downloads directory in work dir
work_downloads = os.path.join(os.getcwd(), 'downloads', '${locus_tag}')
os.makedirs(work_downloads, exist_ok=True)

# Copy only summary table and recreate required UniProt directories.
# This avoids copying the full locus directory while preserving expected layout.
summary_file = os.path.join('${structure_dir}', '${locus_tag}', '${locus_tag}_structure_summary.tsv')
if not os.path.exists(summary_file):
    print(f'Structure summary table not found for ${locus_tag}, skipping.')
    sys.exit(0)

local_summary = os.path.join(work_downloads, os.path.basename(summary_file))
shutil.copy2(summary_file, local_summary)

with open(local_summary, newline='') as fh:
    reader = csv.DictReader(fh, delimiter='\\t')
    for row in reader:
        uniprot_id = (row.get('uniprot_id') or '').strip()
        if uniprot_id:
            os.makedirs(os.path.join(work_downloads, uniprot_id), exist_ok=True)

# Download structures for this single locus_tag (downloads go to parent of locus dir)
parent_dir = os.path.dirname(work_downloads)
structures.download_single_structure(parent_dir, '${locus_tag}')

print(f'Completed structure download for ${locus_tag}')
"""
    
    stub:
    """
    echo "STUB: Downloaded structures for ${locus_tag}"
    """
}

process STRUCTURES_EXTRACT_CHAINS_SINGLE {
    tag "${locus_tag}"
    label 'medium_resources'
    maxForks 10

    input:
    tuple val(locus_tag), path(download_dir), path(structure_dir)
    val organism_name
    val pocket_full_mode

    output:
    val locus_tag, emit: completed_tag
    path "${organism_name}/structures/${locus_tag}", emit: locus_structure_dir, optional: true

    script:
    def base_path = workflow.projectDir.parent
    def pocket_full_mode_py = pocket_full_mode ? 'True' : 'False'
    """#!/usr/bin/env python3

import os
import sys
import shutil

sys.path.insert(0, '${base_path}')
from ftscripts import structures

work_dir = os.getcwd()
locus_tag = '${locus_tag}'

source_locus_dir = os.path.join('${structure_dir}', locus_tag)
dest_locus_dir = os.path.join(work_dir, '${organism_name}', 'structures', locus_tag)
os.makedirs(os.path.dirname(dest_locus_dir), exist_ok=True)

if os.path.exists(source_locus_dir):
    shutil.copytree(source_locus_dir, dest_locus_dir, dirs_exist_ok=True)
else:
    print(f'Warning: source locus directory not found: {source_locus_dir}')
    os.makedirs(dest_locus_dir, exist_ok=True)

if os.path.exists('${download_dir}'):
    shutil.copytree('${download_dir}', dest_locus_dir, dirs_exist_ok=True)
else:
    print(f'Warning: download directory not found for {locus_tag}: ${download_dir}')

if ${pocket_full_mode_py}:
    structures.get_chain_all_pdbs_for_locus(locus_tag, dest_locus_dir)
else:
    structures.get_chain_reference_structure_for_locus(locus_tag, dest_locus_dir)

print(f'Completed chain extraction for {locus_tag}')
"""

    stub:
    """
    mkdir -p ${organism_name}/structures/${locus_tag}
    echo "STUB: Chain extraction for ${locus_tag}"
    """
}

process STRUCTURES_EXTRACT_CHAINS_COLLECT {
    tag "${organism_name}"
    label 'medium_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/structures/**"

    input:
    val organism_name
    val output_path
    path structure_dir
    path extracted_locus_dirs, stageAs: 'extracted/*'

    output:
    path "${organism_name}/structures", emit: structure_dir
    path "${organism_name}/structures/**", emit: all_structures
    val organism_name, emit: organism_name

    script:
    """#!/usr/bin/env python3

import os
import shutil

base_structures = '${structure_dir}'
work_structures = os.path.join(os.getcwd(), '${organism_name}', 'structures')
os.makedirs(work_structures, exist_ok=True)

if os.path.exists(base_structures):
    shutil.copytree(base_structures, work_structures, dirs_exist_ok=True)

extracted_root = 'extracted'
if os.path.exists(extracted_root):
    for item in os.listdir(extracted_root):
        src = os.path.join(extracted_root, item)
        if os.path.isdir(src):
            dst = os.path.join(work_structures, item)
            shutil.copytree(src, dst, dirs_exist_ok=True)

print('Collected extracted chains into unified structures directory')
"""

    stub:
    """
    mkdir -p ${organism_name}/structures/gene_example
    echo "STUB: Collected extracted chains for ${organism_name}"
    """
}

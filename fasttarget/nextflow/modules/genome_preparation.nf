#!/usr/bin/env nextflow

/*
 * Module: Genome Preparation
 * ===========================
 * Prepares genome files from GenBank format
 * Converts to FAA, FFN, FNA, and GFF formats
 */

process GENOME_PREPARATION {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/genome/*"
    
    input:
    path gbk_file
    val organism_name
    val output_path
    val container_engine
    
    output:
    path "${organism_name}/genome/${organism_name}.gbk", emit: gbk
    path "${organism_name}/genome/${organism_name}.faa", emit: faa
    path "${organism_name}/genome/${organism_name}.ffn", emit: ffn
    path "${organism_name}/genome/${organism_name}.fna", emit: fna
    path "${organism_name}/genome/${organism_name}.gff", emit: gff
    path "${organism_name}/genome/*", emit: all_genome_files
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3

import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import files, genome

# Create genome directory in work dir
work_dir = os.getcwd()
genome_dir = os.path.join(work_dir, '${organism_name}', 'genome')
os.makedirs(genome_dir, exist_ok=True)

print(f'Working in: {work_dir}')
print(f'Genome directory: {genome_dir}')

# Create organism genome files in work directory
# Modified to write to local genome/ directory
genome.ref_genome_files('${gbk_file}', genome_dir, '${organism_name}',
                       container_engine='${container_engine}')

print(f'Genome files created in {genome_dir}')
print('Genome preparation completed successfully')
"""
    
    stub:
    """
    mkdir -p ${organism_name}/genome
    touch ${organism_name}/genome/${organism_name}.gbk
    touch ${organism_name}/genome/${organism_name}.faa
    touch ${organism_name}/genome/${organism_name}.ffn
    touch ${organism_name}/genome/${organism_name}.fna
    touch ${organism_name}/genome/${organism_name}.gff
    echo "STUB: Genome preparation for ${organism_name}"
    """
}

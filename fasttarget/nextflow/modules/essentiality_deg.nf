#!/usr/bin/env nextflow

/*
 * Module: Essentiality - DEG Analysis
 * ====================================
 * Runs BLAST against Database of Essential Genes (DEG)
 * 
 * Steps:
 * 1. Run BLASTP search against DEG database
 * 2. Parse results with identity and coverage filters
 * 
 * Input: Organism FAA file, DEG database
 * Output: Essentiality scores for genes
 */

process ESSENTIALITY_DEG {
    tag "${organism_name}"
    label 'blast_process'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/essentiality/**"
    
    input:
    path genome_files
    val organism_name
    val output_path
    val databases_path
    val deg_identity_filter
    val deg_coverage_filter
    val cpus
    
    output:
    path "${organism_name}/essentiality/deg_blast.tsv", emit: blast_results
    path "${organism_name}/essentiality/hit_in_deg.tsv", emit: deg_table
    path "${organism_name}/essentiality/hit_in_deg.csv", emit: deg_csv, optional: true
    path "${organism_name}/essentiality/*", emit: all_essentiality
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import essentiality, files

print('=' * 80)
print('ESSENTIALITY ANALYSIS (DEG)'.center(80))
print('=' * 80)

print('\\nParameters:')
print(f'  - Identity filter: ${deg_identity_filter}%')
print(f'  - Coverage filter: ${deg_coverage_filter}%')
print(f'  - CPUs: ${cpus}')

# Create organism directory structure in work dir
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
essentiality_dir = os.path.join(organism_dir, 'essentiality')
os.makedirs(essentiality_dir, exist_ok=True)

# Create genome directory and copy genome files
import shutil
genome_dir = os.path.join(organism_dir, 'genome')
os.makedirs(genome_dir, exist_ok=True)

print('Copying genome files...')
for genome_file in os.listdir('.'):
    if genome_file.endswith(('.gbk', '.faa', '.fna', '.fasta', '.gff')):
        src = os.path.join(work_dir, genome_file)
        dst = os.path.join(genome_dir, genome_file)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f'  Copied: {genome_file}')

deg_blast_output = os.path.join(essentiality_dir, 'deg_blast.tsv')

if not files.file_check(deg_blast_output):
    print('[1] Running BLASTP search against DEG database...')
    essentiality.essential_deg_blast('${databases_path}', work_dir, '${organism_name}', ${cpus})
    print('  ✓ BLAST search completed')
else:
    print('[1] BLAST results already exist, skipping search')
    print(f'  Found: {deg_blast_output}')

print('[2] Parsing DEG results...')
df_deg = essentiality.deg_parse(
    work_dir,
    '${organism_name}',
    ${deg_identity_filter},
    ${deg_coverage_filter}
)

print(f'\\nEssentiality analysis completed')
print(f'  - Genes with DEG hits: {len(df_deg)}')

# Verify critical output exists and has data
import pandas as pd
deg_file = os.path.join(essentiality_dir, 'hit_in_deg.tsv')

if not os.path.exists(deg_file):
    raise FileNotFoundError(f'Critical file not found: {deg_file}')

df_check = pd.read_csv(deg_file, sep='\\t')
print(f'  ✓ Verified: hit_in_deg.tsv has {len(df_check)} rows')
"""

    stub:
    """
    mkdir -p ${output_path}/${organism_name}/essentiality
    
    # Create dummy BLAST results
    echo -e "qseqid\\tsseqid\\tpident\\tlength\\tmismatch\\tgapopen\\tqstart\\tqend\\tsstart\\tsend\\tevalue\\tbitscore\\tqcovs" > ${output_path}/${organism_name}/essentiality/deg_blast.tsv
    echo -e "gene1\\tDEG10010001\\t85.5\\t300\\t15\\t2\\t1\\t300\\t1\\t300\\t1e-100\\t500\\t95.0" >> ${output_path}/${organism_name}/essentiality/deg_blast.tsv
    
    # Create dummy parsed results
    echo -e "gene\\tdeg_hit\\tdeg_identity\\tdeg_coverage\\tdeg_essential\\ngene1\\tDEG10010001\\t85.5\\t95.0\\tyes" > ${output_path}/${organism_name}/essentiality/hit_in_deg.tsv
    
    echo "STUB: Essentiality analysis for ${organism_name}"
    """
}

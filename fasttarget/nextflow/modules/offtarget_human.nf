#!/usr/bin/env nextflow

/*
 * Module: Offtarget - Human
 * ==========================
 * Runs BLAST against human proteome to identify potential offtargets
 * 
 * Steps:
 * 1. Run BLASTP search against human database
 * 2. Parse BLAST results with filters
 * 
 * Can run in parallel with microbiome and foldseek offtarget modules
 */

process OFFTARGET_HUMAN {
    tag "${organism_name}"
    label 'blast_process'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/offtarget/**"
    
    input:
    path genome_files
    val organism_name
    val output_path
    val databases_path
    val cpus
    
    output:
    path "${organism_name}/offtarget/human_offtarget_blast.tsv", emit: blast_results
    path "${organism_name}/offtarget/human_offtarget.tsv", emit: parsed_table
    path "${organism_name}/offtarget/human_offtarget.csv", emit: parsed_csv, optional: true
    path "${organism_name}/offtarget/*", emit: all_human_offtarget
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import offtargets, files

print('=' * 80)
print('HUMAN OFFTARGET ANALYSIS'.center(80))
print('=' * 80)

# Create organism directory structure in work dir
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
offtarget_dir = os.path.join(organism_dir, 'offtarget')
os.makedirs(offtarget_dir, exist_ok=True)

print(f'Working in: {work_dir}')
print(f'Offtarget directory: {offtarget_dir}')

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

print('[1] Running BLASTP search against human proteome...')
human_blast_output = os.path.join(offtarget_dir, 'human_offtarget_blast.tsv')
offtargets.human_offtarget_blast('${databases_path}', work_dir, '${organism_name}', ${cpus})
print('  ✓ BLAST search completed')

print('[2] Parsing BLAST results...')
df_human = offtargets.human_offtarget_parse(work_dir, '${organism_name}')
print(f'  ✓ Parsed {len(df_human)} genes with human homologs')

print('Human offtarget analysis completed')
"""
    
    stub:
    """
    mkdir -p offtarget
    echo -e "qseqid\\tsseqid\\tpident\\tlength\\tmismatch\\tgapopen\\tqstart\\tqend\\tsstart\\tsend\\tevalue\\tbitscore\\tqcovs" > offtarget/human_offtarget_blast.tsv
    echo -e "gene\\thuman_homolog\\thuman_identity\\thuman_coverage\\ngene1\\tP12345\\t95.5\\t98.0" > offtarget/human_offtarget.tsv
    echo "STUB: Human offtarget for ${organism_name}"
    """
}

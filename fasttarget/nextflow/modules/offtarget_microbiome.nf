#!/usr/bin/env nextflow

/*
 * Module: Offtarget - Microbiome
 * ===============================
 * Runs BLAST against gut microbiome genomes to identify potential offtargets
 * 
 * Steps:
 * 1. Run BLASTP searches against all microbiome species genomes
 * 2. Parse results with identity and coverage filters
 * 3. Generate normalized scores and counts
 * 
 * Can run in parallel with human and foldseek offtarget modules
 */

process OFFTARGET_MICROBIOME {
    tag "${organism_name}"
    label 'blast_process'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/offtarget/**"
    
    input:
    path genome_files
    val organism_name
    val output_path
    val databases_path
    val microbiome_identity_filter
    val microbiome_coverage_filter
    val cpus
    
    output:
    path "${organism_name}/offtarget/species_blast_results/", emit: species_dir
    path "${organism_name}/offtarget/species_blast_results/gut_microbiome_offtarget_norm.tsv", emit: normalized_table
    path "${organism_name}/offtarget/species_blast_results/gut_microbiome_offtarget_counts.tsv", emit: counts_table
    path "${organism_name}/offtarget/species_blast_results/gut_microbiome_genomes_analyzed.tsv", emit: genomes_analyzed
    path "${organism_name}/offtarget/**", emit: all_microbiome_offtarget
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import offtargets

print('=' * 80)
print('MICROBIOME OFFTARGET ANALYSIS'.center(80))
print('=' * 80)

print('\\nParameters:')
print(f'  - Identity filter: ${microbiome_identity_filter}%')
print(f'  - Coverage filter: ${microbiome_coverage_filter}%')
print(f'  - CPUs: ${cpus}')

# Create organism directory structure in work dir
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
offtarget_dir = os.path.join(organism_dir, 'offtarget')
os.makedirs(offtarget_dir, exist_ok=True)

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

print('[1] Running BLASTP searches against microbiome species...')
offtargets.microbiome_offtarget_blast_species('${databases_path}', work_dir, '${organism_name}', ${cpus})
print('  ✓ BLAST searches completed')

print('[2] Parsing and analyzing results...')
df_microbiome_norm, df_microbiome_counts, df_microbiome_total_genomes = offtargets.microbiome_species_parse('${databases_path}', work_dir, '${organism_name}', ${microbiome_identity_filter}, ${microbiome_coverage_filter})

print(f'Microbiome offtarget analysis completed')
print(f'  - Genes analyzed: {len(df_microbiome_norm)}')
print(f'  - Genomes analyzed: {len(df_microbiome_total_genomes)}')
"""
    
    stub:
    """
    mkdir -p offtarget/species_blast_results
    
    # Create dummy species results
    echo -e "gene\tmicrobiome_offtarget_norm\ngene1\t0.15" > offtarget/species_blast_results/gut_microbiome_offtarget_norm.tsv
    echo -e "gene\tmicrobiome_offtarget_count\ngene1\t5" > offtarget/species_blast_results/gut_microbiome_offtarget_counts.tsv
    echo -e "genome_id\tgenome_name\ngut_genome_1\tBacteroides" > offtarget/species_blast_results/gut_microbiome_genomes_analyzed.tsv
    
    # Create a dummy individual result
    echo -e "qseqid\tsseqid\tpident\tqcovs\ngene1\tprotein1\t85.5\t90.0" > offtarget/species_blast_results/MGYG000000001_offtarget.tsv
    
    echo "STUB: Microbiome offtarget for ${organism_name}"
    """
}

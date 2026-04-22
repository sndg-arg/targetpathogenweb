#!/usr/bin/env nextflow

/*
 * Module: Offtarget - Foldseek (Structural)
 * ==========================================
 * Runs Foldseek structural comparison against human structures
 * 
 * Requires structures module to be completed first
 * 
 * Steps:
 * 1. Run Foldseek against human structural database
 * 2. Parse and merge Foldseek results
 * 3. Generate final structure-based offtarget table
 * 
 * Can run in parallel with human and microbiome offtarget modules
 * 
 * Note: User mentioned this part will be modified in the future
 */

process OFFTARGET_FOLDSEEK {
    tag "${organism_name}"
    label 'high_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/offtarget/**"
    
    input:
    path genome_files
    path structure_dir
    val organism_name
    val output_path
    val databases_path
    val container_engine
    val colabfold_all_models
    
    output:
    path "${organism_name}/offtarget/foldseek_results/", emit: foldseek_dir
    path "${organism_name}/offtarget/${organism_name}_final_foldseek_results.tsv", emit: foldseek_table, optional: true
    path "${organism_name}/offtarget/${organism_name}_final_foldseek_colabfold_results.tsv", emit: foldseek_colab_table, optional: true
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
print('FOLDSEEK STRUCTURAL OFFTARGET ANALYSIS'.center(80))
print('=' * 80)

# Create organism directory structure in work dir
import shutil
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
genome_dir = os.path.join(organism_dir, 'genome')
structures_dir_dest = os.path.join(organism_dir, 'structures')
offtarget_dir = os.path.join(organism_dir, 'offtarget')
os.makedirs(genome_dir, exist_ok=True)
os.makedirs(offtarget_dir, exist_ok=True)

# Copy genome files to expected location
print('Copying genome files...')
for genome_file in os.listdir('.'):
    if genome_file.endswith(('.gbk', '.faa', '.fna', '.gff')):
        src = os.path.join(work_dir, genome_file)
        dst = os.path.join(genome_dir, genome_file)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f'  Copied: {genome_file}')

# Copy structures directory from upstream process output (Nextflow channel input)
print('Setting up structures directory...')
staged_structures = '${structure_dir}'
structures_dest = os.path.join(work_dir, '${organism_name}', 'structures')

if os.path.exists(staged_structures):
    if os.path.islink(staged_structures):
        staged_structures = os.path.realpath(staged_structures)
    shutil.copytree(staged_structures, structures_dest, dirs_exist_ok=True)
    print(f'  Copied structures directory from staged input')
    print(f'  Source: {staged_structures}')
    print(f'  Destination: {structures_dest}')
else:
    print(f'  ERROR: Staged structures directory not found: {staged_structures}')
    sys.exit(1)

print('[1] Running Foldseek against human structures...')
foldseek_mapping = offtargets.run_foldseek_human_structures(
    '${databases_path}',
    work_dir,
    '${organism_name}',
    container_engine='${container_engine}'
)
print('  ✓ Foldseek search completed')

print('[2] Parsing Foldseek results...')
results_foldseek_dict = offtargets.foldseek_human_parser(
    work_dir,
    '${organism_name}',
    foldseek_mapping
)

print('[3] Merging Foldseek data...')
mapped_dict_foldseek = offtargets.merge_foldseek_data(
    work_dir,
    '${organism_name}'
)

print('[4] Creating final structure table...')
final_foldseek_df = offtargets.final_foldseek_structure_table(
    work_dir,
    '${organism_name}',
    mapped_dict_foldseek
)

if ${colabfold_all_models ? 'True' : 'False'}:
    print('[5] Running Foldseek with ColabFold structures...')
    foldseek_colab_mapping = offtargets.run_foldseek_human_colabfold_structures(
        '${databases_path}',
        work_dir,
        '${organism_name}',
        container_engine='${container_engine}'
    )

    print('[6] Parsing Foldseek ColabFold results...')
    results_foldseek_colab_dict = offtargets.foldseek_human_colabfold_parser(
        work_dir,
        '${organism_name}',
        foldseek_colab_mapping
    )

    print('[7] Merging Foldseek ColabFold data...')
    mapped_dict_foldseek_colab = offtargets.merge_foldseek_colabfold_data(
        work_dir,
        '${organism_name}'
    )

    print('[8] Creating final ColabFold structure table...')
    final_foldseek_colab_df = offtargets.final_foldseek_colabfold_structure_table(
        work_dir,
        '${organism_name}',
        mapped_dict_foldseek_colab
    )

print(f'Foldseek offtarget analysis completed')
print(f'  - Structures analyzed: {len(final_foldseek_df)}')
"""
    
    stub:
    """
    mkdir -p offtarget/foldseek_results
    echo -e "gene\\tfoldseek_human_match\\tfoldseek_score\\ngene1\\t1A2B_A\\t0.95" > offtarget/foldseek_human_offtarget.tsv
    echo "STUB: Foldseek offtarget for ${organism_name}"
    """
}

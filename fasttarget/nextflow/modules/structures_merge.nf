#!/usr/bin/env nextflow

/*
 * Module: Structures - Merge and Finalize
 * ========================================
 * Stage 4: Merges structure and pocket data into final tables
 * 
 * Steps:
 * 1. Merge structure and pocket data from all genes
 * 2. Create final summary table
 * 
 * Outputs:
 * - *_structure_data.json: Complete structure data dictionary
 * - *_final_structure_summary.tsv: Final summary table for integration
 */

process STRUCTURES_MERGE {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/structures/**"
    
    input:
    path genome_files
    path structure_dir
    val pocket_locus_dirs
    val organism_name
    val output_path
    val full_mode
    val colabfold
    val colabfold_all_models
    
    output:
    path "${organism_name}/structures/${organism_name}_structure_data.json", emit: structure_data_json
    path "${organism_name}/structures/${organism_name}_final_structure_summary.tsv", emit: final_table
    path "${organism_name}/structures/*", emit: all_structure_final
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    def full_mode_py = full_mode ? 'True' : 'False'
    def colabfold_py = colabfold ? 'True' : 'False'
    def colabfold_all_models_py = colabfold_all_models ? 'True' : 'False'
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures

print('=' * 80)
print('STAGE 4: MERGING AND FINALIZATION'.center(80))
print('─' * 80)

# Create organism directory structure in work dir
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
structures_dir = os.path.join(organism_dir, 'structures')
os.makedirs(structures_dir, exist_ok=True)

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

# Copy staged structures from upstream process output (Nextflow channel input)
staged_structures = '${structure_dir}'
if os.path.exists(staged_structures):
    if os.path.islink(staged_structures):
        staged_structures = os.path.realpath(staged_structures)
    print(f'Copying staged structures from: {staged_structures}')
    shutil.copytree(staged_structures, structures_dir, dirs_exist_ok=True)
else:
    print(f'WARNING: staged structures directory not found: {staged_structures}')

# Merge pockets directories from parallel pockets process outputs
pocket_data_flat = ${groovy.json.JsonOutput.toJson(pocket_locus_dirs)}
pocket_data = [(pocket_data_flat[i], pocket_data_flat[i+1]) for i in range(0, len(pocket_data_flat), 2)]

print(f'Merging pockets from {len(pocket_data)} loci...')
merged_loci = 0
for locus_tag, pockets_path in pocket_data:
    pockets_src = pockets_path
    if not os.path.isdir(pockets_src):
        print(f'  WARNING: pockets directory not found for {locus_tag}: {pockets_src}')
        continue

    dest_locus = os.path.join(structures_dir, locus_tag)
    os.makedirs(dest_locus, exist_ok=True)
    pockets_dest = os.path.join(dest_locus, 'pockets')
    shutil.copytree(pockets_src, pockets_dest, dirs_exist_ok=True)
    merged_loci += 1
    print(f'  Merged pockets for locus: {locus_tag}')

print(f'  Total merged pocket loci: {merged_loci}')

print('[4.1] Merging structure and pocket data...')
merged_data = structures.merge_structure_data(
    work_dir,
    '${organism_name}',
    full_mode=${full_mode_py},
    colabfold=${colabfold_py},
    colabfold_all_models=${colabfold_all_models_py}
)
print(f'    ✓ Processed {len(merged_data)} genes')

print('[4.2] Creating final summary table...')
final_df = structures.final_structure_table(
    work_dir,
    '${organism_name}',
    full_mode=${full_mode_py},
    colabfold=${colabfold_py},
    colabfold_all_models=${colabfold_all_models_py}
)

print('\\n' + '=' * 80)
print('STRUCTURE PIPELINE COMPLETED'.center(80))
print('=' * 80)
print(f'\\nResults:')
print(f'  - Total genes: {len(final_df)}')
print(f'  - Genes with structures: {final_df["structure"].notna().sum()}')
print(f'  - Genes with FPocket pockets: {final_df["fpocket_pocket"].notna().sum()}')
print(f'  - Genes with P2Rank pockets: {final_df["p2rank_pocket"].notna().sum()}')
"""
    
    stub:
    """
    mkdir -p ${organism_name}/structures
    touch ${organism_name}/structures/${organism_name}_structure_data.json
    touch ${organism_name}/structures/${organism_name}_final_structure_summary.tsv
    echo "STUB: Structure merge for ${organism_name}"
    """
}

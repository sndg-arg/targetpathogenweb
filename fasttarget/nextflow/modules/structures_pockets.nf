#!/usr/bin/env nextflow

/*
 * Module: Structures - Pocket Detection (Parallel)
 * =================================================
 * Stage 3: Runs FPocket and P2Rank for druggable pocket detection
 * 
 * Uses scatter-gather pattern for maximum parallelization:
 * - Runs FPocket + P2Rank per gene in parallel (up to 50 simultaneously)
 * - Each gene gets dedicated resources (2 CPUs for P2Rank)
 * - Failed genes auto-retry without affecting others
 * 
 * This is the most computationally intensive stage and benefits
 * significantly from parallel execution across multiple genes.
 */

process STRUCTURES_POCKETS_SINGLE {
    tag "${locus_tag}"
    label 'medium_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/structures/*/pockets", overwrite: true


    cpus 2  // Each P2Rank instance gets 2 CPUs
    maxForks 10  // Run up to 10 genes in parallel
    
    errorStrategy 'retry'
    maxRetries 2
    
    input:
    tuple val(locus_tag), path(structures_root)
    val output_path
    val organism_name
    val container_engine
    val full_mode
    val colabfold
    val colabfold_all_models
    val resolution_cutoff
    val coverage_cutoff
    
    output:
    val locus_tag, emit: completed_tag
    path "${organism_name}/structures/${locus_tag}/pockets", type: 'dir', emit: pockets_dir, optional: true
    tuple val(locus_tag), path("${organism_name}/structures/${locus_tag}/pockets"), emit: locus_pockets_dir, optional: true

    script:
    def base_path = workflow.projectDir.parent
    def full_mode_py = full_mode ? 'True' : 'False'
    def colabfold_py = colabfold ? 'True' : 'False'
    def colabfold_all_models_py = colabfold_all_models ? 'True' : 'False'

    """#!/usr/bin/env python3
    
import sys
import os
import shutil

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures

# Setup work directory
work_dir = os.getcwd()

# Copy locus structure directory from upstream channel input to work directory
locus_source = os.path.join('${structures_root}', '${locus_tag}')
locus_dest = os.path.join(work_dir, '${organism_name}', 'structures', '${locus_tag}')

if os.path.exists(locus_source):
    os.makedirs(os.path.dirname(locus_dest), exist_ok=True)
    shutil.copytree(locus_source, locus_dest, dirs_exist_ok=True)
    print(f'Copied ${locus_tag} structure directory from upstream input')
else:
    print(f'WARNING: Structure directory not found: {locus_source}')
    sys.exit(1)

structure_dir = os.path.join(work_dir, '${organism_name}', 'structures')
locus_dir = os.path.join(structure_dir, '${locus_tag}')

print(f'Processing pockets for ${locus_tag}...')

# Run FPocket for this locus
print(f'  [FPocket] ${locus_tag}')
structures.pockets_finder_for_locus(
    locus_dir,
    container_engine='${container_engine}',
    full_mode=${full_mode_py},
    colabfold=${colabfold_py},
    colabfold_all_models=${colabfold_all_models_py},
    resolution_cutoff=${resolution_cutoff},
    coverage_cutoff=${coverage_cutoff}
)

# Run P2Rank for this locus (with 2 CPUs)
print(f'  [P2Rank] ${locus_tag}')
structures.p2rank_finder_for_locus(
    locus_dir,
    cpus=2,
    container_engine='${container_engine}',
    full_mode=${full_mode_py},
    colabfold=${colabfold_py},
    colabfold_all_models=${colabfold_all_models_py},
    resolution_cutoff=${resolution_cutoff},
    coverage_cutoff=${coverage_cutoff}
)

# Keep only pockets in this task output.
# This avoids restaging full structure trees into downstream merge.
for item in os.listdir(locus_dir):
    item_path = os.path.join(locus_dir, item)
    if item == 'pockets':
        continue
    if os.path.isdir(item_path):
        shutil.rmtree(item_path)
    else:
        os.remove(item_path)

print(f'Completed pocket detection for ${locus_tag}')
"""
    
    stub:
    """
    mkdir -p ${output_path}/${organism_name}/structures/${locus_tag}/pockets
    mkdir -p ${output_path}/${organism_name}/structures/${locus_tag}/pockets/AF_example_fpocket
    mkdir -p ${output_path}/${organism_name}/structures/${locus_tag}/pockets/AF_example_p2rank
    touch ${output_path}/${organism_name}/structures/${locus_tag}/pockets/all_pockets.json
    touch ${output_path}/${organism_name}/structures/${locus_tag}/pockets/all_p2rank_pockets.json
    echo "STUB: Pocket detection for ${locus_tag}"
    """
}

process STRUCTURES_POCKETS_COLLECT {
    tag "${organism_name}"
    label 'low_resources'
    
    input:
    val organism_name
    val output_path
    val all_completed_tags
    
    output:
    val organism_name, emit: organism_name
    
    script:
    """
    echo "Pocket detection completed for all ${all_completed_tags.size()} genes"
    echo "Results available in: ${output_path}/${organism_name}/structures/*/pockets/"
    """
    
    stub:
    """
    echo "STUB: Collected pocket results for ${organism_name}"
    """
}

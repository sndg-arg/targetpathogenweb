#!/usr/bin/env nextflow

/*
 * Module: Metabolic Analysis - SBML (MetaGraphTools)
 * ===================================================
 * Analyzes metabolic networks using custom SBML file
 * and MetaGraphTools
 */

process METABOLISM_SBML {
    tag "${organism_name}"
    label 'medium_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/metabolism/*"
    
    input:
    val organism_name
    val output_path
    path gbk_file
    path sbml_file
    path filter_file
    val container_engine
    
    output:
    path "${organism_name}/metabolism/MGT_betweenness_centrality.tsv", emit: centrality
    path "${organism_name}/metabolism/MGT_edges.tsv", emit: edges
    path "${organism_name}/metabolism/MGT_consuming_chokepoints.tsv", emit: consuming
    path "${organism_name}/metabolism/MGT_producing_chokepoints.tsv", emit: producing
    path "${organism_name}/metabolism/MGT_results_*", emit: mgt_results_dir
    path "${organism_name}/metabolism/*", emit: all_metabolism_sbml
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    def filter_arg = filter_file.name != 'NO_FILE' ? "'${filter_file}'" : "None"
    """#!/usr/bin/env python3

import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import pathways

print('=' * 80)
print('Metabolic Analysis - Custom SBML'.center(80))
print('*' * 80)
print('Using SBML file and MetaGraphTools')

filter_file_path = ${filter_arg}

if filter_file_path:
    print(f'SBML file: ${sbml_file}')
    print(f'Filter file: {filter_file_path}')
else:
    print(f'SBML file: ${sbml_file}')
    print('Filter file: Not provided (will use default frequency filter)')

# Create directory structure expected by pathways module
import shutil
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
genome_dir = os.path.join(organism_dir, 'genome')
metabolism_dir = os.path.join(organism_dir, 'metabolism')
os.makedirs(genome_dir, exist_ok=True)
os.makedirs(metabolism_dir, exist_ok=True)

# Copy gbk file to expected location
gbk_dest = os.path.join(genome_dir, '${organism_name}.gbk')
shutil.copy('${gbk_file}', gbk_dest)

# Run metabolic analysis with custom SBML
mgt_bc_df, mgt_degree_df, mgt_consumption_df, mgt_production_df = pathways.run_metabolism_sbml(
    work_dir,
    '${organism_name}',
    '${sbml_file}',
    filter_file_path,
    container_engine='${container_engine}'
)

print('Metabolic analysis (SBML/MetaGraphTools) completed successfully')
print(f'- Betweenness centrality table: {len(mgt_bc_df)} genes')
print(f'- Degree centrality table: {len(mgt_degree_df)} genes')
print(f'- Consumption table: {len(mgt_consumption_df)} genes')
print(f'- Production table: {len(mgt_production_df)} genes')
"""
    
    stub:
    """
    mkdir -p ${organism_name}/metabolism/MGT_results_stub
    touch ${organism_name}/metabolism/MGT_betweenness_centrality.tsv
    touch ${organism_name}/metabolism/MGT_edges.tsv
    touch ${organism_name}/metabolism/MGT_consuming_chokepoints.tsv
    touch ${organism_name}/metabolism/MGT_producing_chokepoints.tsv
    touch ${organism_name}/metabolism/MGT_results_stub/betweenness_centrality.tsv
    touch ${organism_name}/metabolism/MGT_results_stub/chokepoint_genes.tsv
    echo "STUB: Metabolic analysis (SBML) for ${organism_name}"
    """
}

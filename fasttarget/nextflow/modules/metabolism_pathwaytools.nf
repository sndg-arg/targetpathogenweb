#!/usr/bin/env nextflow

/*
 * Module: Metabolic Analysis - Pathway Tools
 * ===========================================
 * Analyzes metabolic networks using Pathway Tools output files
 * (SBML, chokepoints, and smarttable)
 */

process METABOLISM_PATHWAYTOOLS {
    tag "${organism_name}"
    label 'medium_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/metabolism/*"
    
    input:
    val organism_name
    val output_path
    path gbk_file
    path sbml_file
    path chokepoint_file
    path smarttable_file
    path curated_ubiquitous_file, stageAs: 'curated_ubiquitous.txt'
    
    output:
    path "${organism_name}/metabolism/PTOOLS_betweenness_centrality.tsv", emit: centrality
    path "${organism_name}/metabolism/PTOOLS_edges.tsv", emit: edges
    path "${organism_name}/metabolism/PTOOLS_producing_chokepoints.tsv", emit: producing
    path "${organism_name}/metabolism/PTOOLS_consuming_chokepoints.tsv", emit: consuming
    path "${organism_name}/metabolism/PTOOLS_both_chokepoints.tsv", emit: both
    path "${organism_name}/metabolism/network.sif", emit: network_sif, optional: true
    path "${organism_name}/metabolism/network.gpickle", emit: network_gpickle, optional: true
    path "${organism_name}/metabolism/*", emit: all_metabolism_ptools
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3

import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import pathways

print('=' * 80)
print('Metabolic Analysis - Pathway Tools'.center(80))
print('*' * 80)
print('Using Pathway Tools output files')

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

# Check if curated ubiquitous file was provided
curated_ubiq_file = '${curated_ubiquitous_file}' if os.path.exists('${curated_ubiquitous_file}') else None
if curated_ubiq_file:
    print(f'Using curated ubiquitous file: {curated_ubiq_file}')
else:
    print('No curated ubiquitous file provided, will use auto-generated')

# Run metabolic analysis with Pathway Tools files
df_centrality, df_edges, producing_df, consuming_df, both_df = pathways.run_metabolism_ptools(
    work_dir,
    '${organism_name}',
    '${sbml_file}',
    '${chokepoint_file}',
    '${smarttable_file}',
    curated_ubiq_file
)

print('Metabolic analysis (Pathway Tools) completed successfully')
print(f'- Centrality table: {len(df_centrality)} genes')
print(f'- Edges table: {len(df_edges)} interactions')
print(f'- Producing chokepoints: {len(producing_df)} genes')
print(f'- Consuming chokepoints: {len(consuming_df)} genes')
print(f'- Both chokepoints: {len(both_df)} genes')
"""
    
    stub:
    """
    mkdir -p ${organism_name}/metabolism
    touch ${organism_name}/metabolism/PTOOLS_betweenness_centrality.tsv
    touch ${organism_name}/metabolism/PTOOLS_edges.tsv
    touch ${organism_name}/metabolism/PTOOLS_producing_chokepoints.tsv
    touch ${organism_name}/metabolism/PTOOLS_consuming_chokepoints.tsv
    touch ${organism_name}/metabolism/PTOOLS_both_chokepoints.tsv
    touch ${organism_name}/metabolism/network.sif
    touch ${organism_name}/metabolism/network.gpickle
    echo "STUB: Metabolic analysis (Pathway Tools) for ${organism_name}"
    """
}

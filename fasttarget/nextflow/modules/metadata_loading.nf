#!/usr/bin/env nextflow

/*
 * Module: Metadata Loading
 * =========================
 * Loads user-provided metadata tables from configuration
 * 
 * Steps:
 * 1. Copy metadata files to organism metadata directory
 * 2. Load tables and detect separator (tab, comma, semicolon)
 * 3. Return DataFrames ready for final merge
 * 
 * Input: List of metadata file paths from config
 * Output: Loaded metadata dataframes
 */

process METADATA_LOADING {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}/${organism_name}", mode: 'copy', pattern: "metadata/*"
    
    input:
    val organism_name
    val output_path
    path metadata_files
    
    output:
    path "metadata/*", emit: metadata_copies
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    def metadata_paths = metadata_files.collect { it.toString() }.join(' ')
    """#!/usr/bin/env python3

import sys
import os
import shutil

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

import pandas as pd
from ftscripts import files

print('=' * 80)
print('METADATA LOADING'.center(80))
print('=' * 80)

# Create metadata directory in work dir
work_dir = os.getcwd()
metadata_dir = os.path.join(work_dir, 'metadata')
os.makedirs(metadata_dir, exist_ok=True)

print(f'Working in: {work_dir}')
print(f'Metadata directory: {metadata_dir}')

metadata_files = '${metadata_paths}'.split()
metadata_dfs = []

for table_path in metadata_files:
    print(f'[{len(metadata_dfs) + 1}] Loading metadata table: {table_path}')
    
    # Copy to metadata directory
    dest_path = os.path.join(metadata_dir, os.path.basename(table_path))
    shutil.copy(table_path, dest_path)
    print(f'  ✓ Copied to: {dest_path}')
    
    # Detect separator
    with open(table_path, 'r') as file:
        first_line = file.readline()
        if '\\t' in first_line:
            sep = '\\t'
        elif ',' in first_line:
            sep = ','
        elif ';' in first_line:
            sep = ';'
        else:
            raise ValueError(f'Invalid file format for {table_path}. Only CSV and TSV metadata files are supported.')
    
    # Load dataframe
    df_meta = pd.read_csv(table_path, header=0, sep=sep)
    print(f'  ✓ Loaded {len(df_meta)} rows with {len(df_meta.columns)} columns')
    print(f'  Columns: {", ".join(df_meta.columns.tolist())}')
    
    # Validate 'gene' column exists
    if 'gene' not in df_meta.columns:
        raise ValueError(f'Metadata table must have a "gene" column: {table_path}')
    
    metadata_dfs.append(df_meta)

print(f'Metadata loading completed')
print(f'  - Total metadata tables: {len(metadata_dfs)}')

"""
    
    stub:
    """
    mkdir -p metadata
    
    # Create dummy metadata files
    echo -e "gene\\tcustom_property\\ngene1\\tvalue1" > metadata/user_metadata_1.tsv
    
    echo "STUB: Metadata loading for ${organism_name}"
    """
}

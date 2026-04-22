#!/usr/bin/env nextflow

/*
 * Module: Final Merge and Results
 * ================================
 * Merges all module DataFrames into final results table
 * 
 * Steps:
 * 1. Collect all analysis DataFrames from previous modules
 * 2. Merge on 'gene' column (left join to preserve all genes)
 * 3. Save final results table
 * 4. Generate individual tables for Target Pathogen import
 * 
 * Input: All analysis DataFrames from modules
 * Output: Final merged table + tables_for_TP directory
 */

process MERGE_FINAL_RESULTS {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}/${organism_name}", mode: 'copy', pattern: "${organism_name}_results_*/**"
    
    input:
    val organism_name
    val output_path
    path gbk_file
    val table_files
    
    output:
    path "${organism_name}_results_*/${organism_name}_results_table.tsv", emit: final_table
    path "${organism_name}_results_*/tables_for_TP/*", emit: tp_tables, optional: true
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    def timestamp = new java.text.SimpleDateFormat('yyyy-MM-dd-HH-mm').format(new Date())
    def table_files_json = groovy.json.JsonOutput.toJson(table_files.collect { it.toString() })
    results_dir = "${organism_name}_results_${timestamp}"
    """#!/usr/bin/env python3
    
import sys
import os
from datetime import datetime
import json
import re

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

import pandas as pd
from ftscripts import metadata, files

print('=' * 80)
print('FINAL RESULTS MERGE'.center(80))
print('=' * 80)

organism_name = '${organism_name}'
results_dir = '${results_dir}'
results_path = results_dir
gbk_file = '${gbk_file}'
table_files = json.loads('''${table_files_json}''')

os.makedirs(results_path, exist_ok=True)
print(f'Results directory: {results_path}')
print(f'Staged input tables: {len(table_files)}')

# List of all possible output tables from modules
tables = []
base_table = None
metadata_tables = []
metadata_table_ids = set()

def genome_locus_tags_from_gbk(path):
    # Parse locus_tag qualifiers directly from GBK text to avoid extra deps.
    locus_tags = []
    seen = set()
    pattern = re.compile(r'/locus_tag="([^"]+)"')
    if not os.path.exists(path):
        print(f'  Warning: genome GBK not found for gene filtering: {path}')
        return seen
    with open(path, 'r', errors='ignore') as fh:
        for line in fh:
            match = pattern.search(line)
            if match:
                tag = match.group(1).strip()
                if tag and tag not in seen:
                    seen.add(tag)
                    locus_tags.append(tag)
    print(f'  Genome locus tags loaded: {len(locus_tags)}')
    return seen

def filter_to_genome_genes(df, name, allowed_genes):
    if df is None or 'gene' not in df.columns:
        return df
    before = len(df)
    filtered = df[df['gene'].isin(allowed_genes)].copy()
    after = len(filtered)
    if before != after:
        print(f'  - Filtered {name}: {before} -> {after} rows (non-genome genes removed)')
    return filtered

# Helper function to load if exists
def load_table(path, name):
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, sep='\\t')
            print(f'  ✓ Loaded {name}: {len(df)} rows, {len(df.columns)} columns')
            return df
        except Exception as e:
            print(f'  ✗ Failed to load {name}: {e}')
            return None
    else:
        print(f'  - Skipped {name} (not found)')
        return None

# Metadata loader aligned with standalone fasttarget.py:
# accept any extension and detect delimiter from first line.
def load_metadata_table(path, name):
    if not os.path.exists(path):
        print(f'  - Skipped {name} (not found)')
        return None
    try:
        with open(path, 'r') as fh:
            first_line = fh.readline()
        if '\\t' in first_line:
            sep = '\\t'
        elif ',' in first_line:
            sep = ','
        elif ';' in first_line:
            sep = ';'
        else:
            raise ValueError('Invalid metadata file format. Only tab/comma/semicolon separators are supported.')

        df = pd.read_csv(path, sep=sep)
        print(f'  ✓ Loaded {name}: {len(df)} rows, {len(df.columns)} columns (sep={repr(sep)})')
        return df
    except Exception as e:
        print(f'  ✗ Failed to load {name}: {e}')
        return None

print('[1] Loading analysis results...')
print('')
allowed_genes = genome_locus_tags_from_gbk(gbk_file)

known_tables = {
    f'{organism_name}_gene_name.tsv': 'Gene names',
    'PTOOLS_betweenness_centrality.tsv': 'PTOOLS betweenness',
    'PTOOLS_producing_chokepoints.tsv': 'PTOOLS producing',
    'PTOOLS_consuming_chokepoints.tsv': 'PTOOLS consuming',
    'PTOOLS_both_chokepoints.tsv': 'PTOOLS both',
    'PTOOLS_edges.tsv': 'PTOOLS edges',
    'MGT_betweenness_centrality.tsv': 'MGT betweenness',
    'MGT_producing_chokepoints.tsv': 'MGT producing',
    'MGT_consuming_chokepoints.tsv': 'MGT consuming',
    'MGT_edges.tsv': 'MGT edges',
    f'{organism_name}_final_structure_summary.tsv': 'Structures',
    'core_roary.tsv': 'Roary',
    'core_corecruncher.tsv': 'CoreCruncher',
    'human_offtarget.tsv': 'Human offtarget',
    'gut_microbiome_offtarget_counts.tsv': 'Microbiome counts',
    'gut_microbiome_offtarget_norm.tsv': 'Microbiome normalized',
    'gut_microbiome_genomes_analyzed.tsv': 'Microbiome genomes',
    f'{organism_name}_final_foldseek_results.tsv': 'Foldseek offtarget',
    f'{organism_name}_final_foldseek_colabfold_results.tsv': 'Foldseek offtarget ColabFold',
    'hit_in_deg.tsv': 'DEG essentiality',
    'psortb_localization.tsv': 'PSortB localization',
}

seen = set()
for table_path in table_files:
    if not os.path.exists(table_path):
        continue
    basename = os.path.basename(table_path)
    if basename in seen:
        continue
    seen.add(basename)

    # Metadata from METADATA_LOADING is staged under metadata/*
    if '/metadata/' in table_path or table_path.startswith('metadata/'):
        meta_df = load_metadata_table(table_path, f'Metadata: {basename}')
        if meta_df is not None:
            meta_df = filter_to_genome_genes(meta_df, f'Metadata: {basename}', allowed_genes)
            metadata_tables.append(meta_df)
            metadata_table_ids.add(id(meta_df))
            tables.append(meta_df)
        continue

    if basename in known_tables:
        df = load_table(table_path, known_tables[basename])
        if df is not None:
            df = filter_to_genome_genes(df, known_tables[basename], allowed_genes)
            if basename == f'{organism_name}_gene_name.tsv':
                base_table = df
            tables.append(df)

print(f'[2] Merging {len(tables)} tables...')

if len(tables) == 0:
    raise ValueError('No tables found to merge!')

# Merge all tables on 'gene' column.
# Force gene_name table as base when available to keep one row per pipeline gene.
if base_table is not None:
    combined_df = base_table
    merge_sources = [df for df in tables if df is not base_table]
    print('  Using gene_name table as merge base')
else:
    # Fallback: avoid metadata as base.
    # Choose the smallest non-metadata gene table to preserve expected gene cardinality.
    non_metadata_candidates = []
    for df in tables:
        if df is None:
            continue
        if 'gene' not in df.columns:
            continue
        if id(df) in metadata_table_ids:
            continue
        non_metadata_candidates.append(df)

    if non_metadata_candidates:
        base_table = min(non_metadata_candidates, key=lambda x: len(x))
        combined_df = base_table
        merge_sources = [df for df in tables if df is not base_table]
        print('  Warning: gene_name table not found; using smallest non-metadata gene table as base')
    else:
        combined_df = tables[0]
        merge_sources = tables[1:]
        print('  Warning: no non-metadata gene table found; using first available table as base')

print(f'  Starting with: {combined_df.shape}')

if 'gene' in combined_df.columns:
    before_base = len(combined_df)
    combined_df = combined_df[combined_df['gene'].isin(allowed_genes)].copy()
    if before_base != len(combined_df):
        print(f'  Base table filtered to genome genes: {before_base} -> {len(combined_df)}')

for i, df in enumerate(merge_sources, 1):
    if df is not None and 'gene' in df.columns:
        if df['gene'].duplicated().any():
            dup_count = int(df['gene'].duplicated().sum())
            print(f'  [{i}] Warning: {dup_count} duplicated gene rows detected; keeping first occurrence')
            df = df.drop_duplicates(subset=['gene'], keep='first')
        before_cols = len(combined_df.columns)
        combined_df = pd.merge(combined_df, df, on='gene', how='left')
        after_cols = len(combined_df.columns)
        print(f'  [{i}] Merged: +{after_cols - before_cols} columns → {combined_df.shape}')

# Save final results table
results_table_path = os.path.join(results_path, f'{organism_name}_results_table.tsv')
combined_df.to_csv(results_table_path, sep='\\t', index=False)

print(f'[3] Final results table saved')
print(f'  Path: {results_table_path}')
print(f'  Shape: {combined_df.shape}')
print(f'  Columns: {len(combined_df.columns)}')

# Generate tables for Target Pathogen
print('[4] Creating metadata tables for Target Pathogen...')
metadata.tables_for_TP(organism_name, results_path)

tp_tables_path = os.path.join(results_path, 'tables_for_TP')
if os.path.exists(tp_tables_path):
    tp_count = len([f for f in os.listdir(tp_tables_path) if f.endswith('.tsv')])
    print(f'  ✓ Created {tp_count} individual tables in tables_for_TP/')

print('\\n' + '=' * 80)
print('FASTTARGET PIPELINE COMPLETED'.center(80))
print('=' * 80)
"""
    
    stub:
    def timestamp = new java.text.SimpleDateFormat('yyyy-MM-dd-HH-mm').format(new Date())
    def stub_results_dir = "${organism_name}_results_${timestamp}"
    """
    mkdir -p ${stub_results_dir}/tables_for_TP
    
    # Create dummy final results table
    echo -e "gene\\tgene_name\\tcore\\tessential\\ngene1\\tprotein1\\ttrue\\ttrue" > ${stub_results_dir}/${organism_name}_results_table.tsv
    
    # Create dummy TP tables
    echo -e "gene\\ngene1" > ${stub_results_dir}/tables_for_TP/gene_name.tsv
    echo -e "gene\\ngene1" > ${stub_results_dir}/tables_for_TP/core_corecruncher.tsv
    echo -e "gene\\ngene1" > ${stub_results_dir}/tables_for_TP/hit_in_deg.tsv
    
    echo "STUB: Final merge for ${organism_name}"
    """
}

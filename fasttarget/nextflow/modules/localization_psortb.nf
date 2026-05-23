#!/usr/bin/env nextflow

/*
 * Module: Localization - PSortB
 * ==============================
 * Predicts subcellular localization using PSortB
 * 
 * Steps:
 * 1. Run PSortB prediction on organism proteome
 * 2. Parse results into tabular format
 * 
 * Input: Organism FAA file, gram type (positive/negative)
 * Output: Localization predictions for all proteins
 */

process LOCALIZATION_PSORTB {
    tag "${organism_name}"
    label 'medium_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/localization/*"
    
    input:
    path genome_files
    val organism_name
    val output_path
    val gram_type
    val container_engine
    
    output:
    path "${organism_name}/localization/*_psortb_*.txt", emit: psortb_raw
    path "${organism_name}/localization/psortb_localization.tsv", emit: localization_table
    path "${organism_name}/localization/psortb_localization.csv", emit: localization_csv, optional: true
    path "${organism_name}/localization/*", emit: all_localization
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import genome

print('=' * 80)
print('LOCALIZATION PREDICTION (PSortB)'.center(80))
print('=' * 80)

print('\\nParameters:')
print(f'  - Gram type: ${gram_type}')

# Create directory structure expected by ftscripts
import shutil
work_dir = os.getcwd()
organism_dir = os.path.join(work_dir, '${organism_name}')
genome_dir = os.path.join(organism_dir, 'genome')
localization_dir = os.path.join(organism_dir, 'localization')
os.makedirs(genome_dir, exist_ok=True)
os.makedirs(localization_dir, exist_ok=True)

# Copy all genome files to expected location
print('Copying genome files...')
for genome_file in os.listdir('.'):
    if genome_file.endswith(('.gbk', '.faa', '.fna', '.fasta', '.gff')):
        src = os.path.join(work_dir, genome_file)
        dst = os.path.join(genome_dir, genome_file)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f'  Copied: {genome_file}')

print('[1] Running PSortB prediction...')
df_psort = genome.localization_prediction(
    work_dir,
    '${organism_name}',
    '${gram_type}',
    container_engine='${container_engine}'
)

print(f'Localization prediction completed')
print(f'  - Proteins analyzed: {len(df_psort)}')

# Get localization directory created by the function
localization_dir = os.path.join(work_dir, '${organism_name}', 'localization')

# Verify critical output exists and has data
import pandas as pd
psort_file = os.path.join(localization_dir, 'psortb_localization.tsv')

if not os.path.exists(psort_file):
    raise FileNotFoundError(f'Critical file not found: {psort_file}')

df_check = pd.read_csv(psort_file, sep='\\t')
if len(df_check) == 0:
    raise ValueError(f'No data in localization file: {psort_file}')

print(f'  ✓ Verified: psortb_localization.tsv has {len(df_check)} proteins')

# Count localizations
if 'localization' in df_check.columns:
    loc_counts = df_check['localization'].value_counts()
    print('\\n  Localization distribution:')
    for loc, count in loc_counts.items():
        print(f'    - {loc}: {count}')
"""
    
    stub:
    """
    mkdir -p ${organism_name}/localization
    
    # Create dummy PSortB raw output
    TIMESTAMP=\$(date +%Y%m%d%H%M%S)
    echo "SeqID    Localization    Score" > ${organism_name}/localization/\${TIMESTAMP}_psortb_gram${gram_type}.txt
    echo "gene1    Cytoplasmic     10.00" >> ${organism_name}/localization/\${TIMESTAMP}_psortb_gram${gram_type}.txt
    echo "gene2    CytoplasmicMembrane    9.50" >> ${organism_name}/localization/\${TIMESTAMP}_psortb_gram${gram_type}.txt
    
    # Create dummy parsed results
    echo -e "gene\\tlocalization\\tpsortb_score\\ngene1\\tCytoplasmic\\t10.00\\ngene2\\tCytoplasmicMembrane\\t9.50" > ${organism_name}/localization/psortb_localization.tsv
    
    echo "STUB: Localization prediction for ${organism_name}"
    """
}

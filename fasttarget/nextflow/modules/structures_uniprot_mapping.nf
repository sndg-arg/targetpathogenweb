#!/usr/bin/env nextflow

/*
 * Module: Structures - UniProt Mapping
 * =====================================
 * Stage 1: Downloads UniProt proteome data and maps organism genes to UniProt IDs
 * 
 * Steps:
 * 1. Download UniProt species data
 * 2. Parse UniProt data into FASTA files
 * 3. Cluster species proteome with CD-HIT
 * 4. Create BLAST databases
 * 5. Run BLAST searches
 * 6. Map organism genes to UniProt IDs
 */

process STRUCTURES_UNIPROT_MAPPING {
    tag "${organism_name}"
    label 'high_resources'
    publishDir "${output_path}", mode: 'copy', pattern: "${organism_name}/structures/**"
    
    input:
    val organism_name
    val output_path
    val specie_taxid
    val strain_taxid
    val cpus
    path faa
    path gbk
    
    output:
    path "${organism_name}/structures/uniprot_files", emit: uniprot_dir
    path "${organism_name}/structures/uniprot_files/uniprot_*_id_mapping.json", emit: mapping_file
    path "${organism_name}/structures/**", emit: all_structures
    val organism_name, emit: organism_name
    
    script:
    def base_path = workflow.projectDir.parent
    """#!/usr/bin/env python3
    
import sys
import os

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures

print('=' * 80)
print('STAGE 1: UNIPROT PROTEOME ACQUISITION AND MAPPING'.center(80))
print('─' * 80)

# Setup work directory structure
work_dir = os.getcwd()
structures_dir = os.path.join(work_dir, '${organism_name}', 'structures')
uniprot_dir = os.path.join(structures_dir, 'uniprot_files')
genome_dir = os.path.join(work_dir, '${organism_name}', 'genome')
os.makedirs(uniprot_dir, exist_ok=True)
os.makedirs(genome_dir, exist_ok=True)

print(f'Working in: {work_dir}')
print(f'Structures directory: {structures_dir}')

# Copy the staged FAA file to expected location
import shutil

faa_path = '${faa}'
target_file_faa = os.path.join(genome_dir, os.path.basename(faa_path))
shutil.copy2(faa_path, target_file_faa)
print(f'Copied genome file: {os.path.basename(faa_path)}')

gbk_path = '${gbk}'
target_file_gbk = os.path.join(genome_dir, os.path.basename(gbk_path))
shutil.copy2(gbk_path, target_file_gbk)
print(f'Copied genome file: {os.path.basename(gbk_path)}')

print('[1.1] Downloading UniProt species data (TaxID: ${specie_taxid})...')
structures.download_species_uniprot_data(work_dir, '${organism_name}', ${specie_taxid})

print('[1.2] Parsing UniProt data into FASTA files...')
uniprot_file = os.path.join(uniprot_dir, f"uniprot_specie_taxid_${specie_taxid}_data.tsv")
structures.parse_uniprot_species_data(uniprot_file, ${specie_taxid}, ${strain_taxid})

print('[1.3] Clustering species proteome with CD-HIT...')
structures.cluster_uniprot_specie(work_dir, '${organism_name}', ${specie_taxid})

print('[1.4] Creating BLAST databases...')
structures.create_uniprot_blast_db(work_dir, '${organism_name}', ${specie_taxid}, ${strain_taxid})

print('[1.5] Running BLAST searches against UniProt databases...')
structures.uniprot_proteome_blast(work_dir, '${organism_name}', ${specie_taxid}, ${strain_taxid}, cpus=${cpus})

print('[1.6] Mapping organism genes to UniProt IDs...')
mapping_dict = structures.uniprot_proteome_mapping(work_dir, '${organism_name}', ${specie_taxid}, ${strain_taxid})
print(f'    ✓ Mapped {len(mapping_dict)} genes to UniProt IDs')

print('\\nStage 1 completed successfully')
"""
    
    stub:
    """
    mkdir -p structures/uniprot_files
    touch structures/uniprot_files/uniprot_test_id_mapping.json
    touch structures/uniprot_files/uniprot_specie_taxid_${specie_taxid}_data.tsv
    echo "STUB: UniProt mapping for ${organism_name}"
    """
}

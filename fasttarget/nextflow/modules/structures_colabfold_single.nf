#!/usr/bin/env nextflow

/*
 * Module: Structures - ColabFold (Parallelized)
 * ==============================================
 * Stage 2.5: Generates ColabFold models (optional) - ONE PROTEIN PER TASK
 *
 * Runs either:
 * - generate_colabfold_missing_single (only missing structures)
 * - generate_colabfold_all_single (all proteins)
 *
 * Each task processes a single locus_tag independently in its isolated working directory.
 * No race conditions, no shared state, full parallelization across GPU nodes.
 */

process COLABFOLD_SINGLE {
    tag "${locus_tag}"
    label 'gpu_process'

    input:
    tuple val(locus_tag), path(locus_structure_dir)
    val organism_name
    val output_path
    path gbk_file
    val amber_option
    val gpu_option
    val colabfold_all_models

    output:
    tuple val(locus_tag), path("${organism_name}/structures/${locus_tag}/CB_*.pdb"), emit: colabfold_cb_results, optional: true
    tuple val(locus_tag), path("${organism_name}/structures/${locus_tag}/colabfold_models"), emit: colabfold_models_results, optional: true
    tuple val(locus_tag), path("${organism_name}/structures/${locus_tag}/${locus_tag}_structure_summary.tsv"), emit: colabfold_summary_results, optional: true

    script:
    def base_path = workflow.projectDir.parent
    def amber_option_py = amber_option ? 'True' : 'False'
    def gpu_option_py = gpu_option ? 'True' : 'False'
    def colabfold_all_models_py = colabfold_all_models ? 'True' : 'False'
    """#!/usr/bin/env python3

import sys
import os
import shutil

# Add parent directory to path to import ftscripts
sys.path.insert(0, '${base_path}')

from ftscripts import structures, files

# Define locus_tag first
locus_tag = '${locus_tag}'

print('=' * 80)
print(f'COLABFOLD SINGLE: Processing {locus_tag}'.center(80))
print('─' * 80)

# Setup work directory for this protein
work_dir = os.getcwd()
locus_structure_dir = os.path.realpath('${locus_structure_dir}')
organism_dir = os.path.join(work_dir, '${organism_name}')
structures_dir = os.path.join(organism_dir, 'structures')
genome_dir = os.path.join(organism_dir, 'genome')
os.makedirs(structures_dir, exist_ok=True)
os.makedirs(genome_dir, exist_ok=True)

# Load UniProt mapping
proteome_ids_file = os.path.join(os.path.dirname(locus_structure_dir), 'uniprot_files', f'uniprot_${organism_name}_id_mapping.json')
if files.file_check(proteome_ids_file):
    map_results = files.json_to_dict(proteome_ids_file)
else:
    map_results = {}
    print(f'WARNING: UniProt ID mapping file not found: {proteome_ids_file}')

# Copy input structure to work directory
task_locus_dir = os.path.join(structures_dir, locus_tag)
if os.path.exists(locus_structure_dir):
    os.makedirs(task_locus_dir, exist_ok=True)

    def link_or_copy(src, dst):
        src_real = os.path.realpath(src)
        try:
            os.symlink(src_real, dst)
            return 'symlink'
        except OSError:
            if os.path.isdir(src_real):
                shutil.copytree(src_real, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src_real, dst)
            return 'copy'

    linked_items = 0
    copied_items = 0
    for item in os.listdir(locus_structure_dir):
        src = os.path.join(locus_structure_dir, item)
        dst = os.path.join(task_locus_dir, item)

        if os.path.lexists(dst):
            continue

        # Mutable in this stage: summary/fasta and colabfold_models.
        # Everything else is read-only context and can be linked.
        if os.path.isdir(src):
            if item == 'colabfold_models':
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied_items += 1
            else:
                mode = link_or_copy(src, dst)
                if mode == 'symlink':
                    linked_items += 1
                else:
                    copied_items += 1
        else:
            if item.endswith('_structure_summary.tsv') or item.endswith('.fasta'):
                shutil.copy2(src, dst)
                copied_items += 1
            else:
                mode = link_or_copy(src, dst)
                if mode == 'symlink':
                    linked_items += 1
                else:
                    copied_items += 1

    print(f'Prepared locus structure for {locus_tag} (linked={linked_items}, copied={copied_items})')
else:
    print(f'ERROR: Input structure directory not found: {locus_structure_dir}')
    sys.exit(1)

# Copy GBK file for sequence extraction
gbk_source = '${gbk_file}'
gbk_dest = os.path.join(genome_dir, '${organism_name}.gbk')
shutil.copy2(gbk_source, gbk_dest)
print(f'Copied GBK file: {os.path.basename(gbk_dest)}')

# Run ColabFold
print(f'[2.5] Running ColabFold for {locus_tag}...')

if ${colabfold_all_models_py}:
    try:
        structures.generate_colabfold_all_single(
            locus_tag,
            work_dir,
            '${organism_name}',
            structures_dir,
            map_results,
            amber_option=${amber_option_py},
            gpu_option=${gpu_option_py}
        )
    except Exception as e:
        with open(os.path.join(task_locus_dir, "colabfold_failed.txt"), "w") as fh:
            fh.write(str(e) + "\n")
        print(f"WARNING: ColabFold failed for {locus_tag}: {e}")

else:
    try:
        structures.generate_colabfold_missing_single(
            locus_tag,
            work_dir,
            '${organism_name}',
            structures_dir,
            map_results,
            amber_option=${amber_option_py},
            gpu_option=${gpu_option_py}
        )
    except Exception as e:
        with open(os.path.join(task_locus_dir, "colabfold_failed.txt"), "w") as fh:
            fh.write(str(e) + "\n")
        print(f"WARNING: ColabFold failed for {locus_tag}: {e}")    
        
# Check canonical CB model generated by pipeline code (do not create it here).
relaxed_file = os.path.join(task_locus_dir, f"CB_{locus_tag}_relaxed1.pdb")
unrelaxed_file = os.path.join(task_locus_dir, f"CB_{locus_tag}_unrelaxed1.pdb")
colabfold_models_dir = os.path.join(task_locus_dir, 'colabfold_models')

if os.path.exists(relaxed_file):
    print(f'Canonical ColabFold model ready: {os.path.basename(relaxed_file)}')
elif os.path.exists(unrelaxed_file):
    print(f'Canonical ColabFold model ready: {os.path.basename(unrelaxed_file)}')
else:
    print(f'INFO: No canonical CB model generated for {locus_tag}')

if os.path.isdir(colabfold_models_dir):
    print(f'ColabFold artifacts available: {colabfold_models_dir}')
else:
    print(f'INFO: No colabfold_models directory for {locus_tag}')

print(f'COLABFOLD_SINGLE completed successfully for {locus_tag}')
"""

    stub:
    """
    mkdir -p ${organism_name}/structures/${locus_tag}/colabfold_models
    touch ${organism_name}/structures/${locus_tag}/CB_${locus_tag}_unrelaxed1.pdb
    echo "STUB: ColabFold model for ${locus_tag}"
    """
}


process COLABFOLD_COLLECT {
    tag "${organism_name}"
    label 'low_resources'
    publishDir "${output_path}/${organism_name}", mode: 'copy', pattern: "structures/**"

    input:
    val organism_name
    val output_path
    path structure_dir
    val colabfold_cb_results
    val colabfold_models_results
    val colabfold_summary_results

    output:
    path "${organism_name}/structures", emit: structure_dir
    path "${organism_name}/structures/**", emit: all_structures
    val organism_name, emit: organism_name

    script:
    """#!/usr/bin/env python3

import os
import shutil
from pathlib import Path

print('=' * 80)
print('STAGE 2.5 COLLECT: Merging ColabFold results'.center(80))
print('─' * 80)

organism_name = '${organism_name}'
base_path = os.path.join(organism_name, 'structures')

# Ensure output directory exists
os.makedirs(base_path, exist_ok=True)

# Parse ColabFold results first to identify loci that must be materialized.
cb_data_flat = ${groovy.json.JsonOutput.toJson(colabfold_cb_results)}
models_data_flat = ${groovy.json.JsonOutput.toJson(colabfold_models_results)}
summary_data_flat = ${groovy.json.JsonOutput.toJson(colabfold_summary_results)}

# Convert flat list into pairs: [tag1, path1, tag2, path2, ...] -> [(tag1, path1), (tag2, path2), ...]
cb_data = [(cb_data_flat[i], cb_data_flat[i+1]) for i in range(0, len(cb_data_flat), 2)]
models_data = [(models_data_flat[i], models_data_flat[i+1]) for i in range(0, len(models_data_flat), 2)]
summary_data = [(summary_data_flat[i], summary_data_flat[i+1]) for i in range(0, len(summary_data_flat), 2)]
loci_to_update = set([x[0] for x in cb_data] + [x[0] for x in models_data] + [x[0] for x in summary_data])

print(f'Processing ColabFold outputs... CB files: {len(cb_data)} | models dirs: {len(models_data)} | summaries: {len(summary_data)}')

# Stage existing structures from upstream:
# - loci to update -> copy (writable)
# - everything else -> symlink (read-only passthrough)
staged_structures = '${structure_dir}'
if os.path.exists(staged_structures):
    if os.path.islink(staged_structures):
        staged_structures = os.path.realpath(staged_structures)
    print(f'Staging existing structures from: {staged_structures}')

    linked_items = 0
    copied_items = 0

    def link_or_copy(src, dst):
        try:
            os.symlink(src, dst)
            return 'symlink'
        except OSError:
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            return 'copy'

    for item in os.listdir(staged_structures):
        src_path = os.path.join(staged_structures, item)
        dst_path = os.path.join(base_path, item)

        if os.path.lexists(dst_path):
            continue

        if item in loci_to_update and os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            copied_items += 1
        else:
            mode = link_or_copy(src_path, dst_path)
            if mode == 'symlink':
                linked_items += 1
            else:
                copied_items += 1

    print(f'Staged structures to {base_path} (linked={linked_items}, copied={copied_items})')
else:
    print(f'WARNING: input structures directory not found: {staged_structures}')

cb_merged_count = 0
models_merged_count = 0
summary_merged_count = 0
failed_count = 0

for locus_tag, cb_file in cb_data:
    cb_path = Path(cb_file)
    if not cb_path.exists():
        print(f'WARNING: CB model not found for {locus_tag} at {cb_file}')
        failed_count += 1
        continue

    locus_structure_dir = os.path.join(base_path, locus_tag)
    if os.path.islink(locus_structure_dir):
        source_dir = os.path.realpath(locus_structure_dir)
        os.unlink(locus_structure_dir)
        shutil.copytree(source_dir, locus_structure_dir, dirs_exist_ok=True)
    os.makedirs(locus_structure_dir, exist_ok=True)
    dest_pdb = os.path.join(locus_structure_dir, cb_path.name)
    shutil.copy2(cb_path, dest_pdb)
    print(f'Added canonical CB model for {locus_tag}: {cb_path.name}')
    cb_merged_count += 1

for locus_tag, models_dir in models_data:
    models_src = Path(models_dir)
    if not models_src.exists() or not models_src.is_dir():
        print(f'WARNING: colabfold_models directory not found for {locus_tag} at {models_dir}')
        failed_count += 1
        continue

    locus_structure_dir = os.path.join(base_path, locus_tag)
    if os.path.islink(locus_structure_dir):
        source_dir = os.path.realpath(locus_structure_dir)
        os.unlink(locus_structure_dir)
        shutil.copytree(source_dir, locus_structure_dir, dirs_exist_ok=True)
    os.makedirs(locus_structure_dir, exist_ok=True)
    models_dest = os.path.join(locus_structure_dir, 'colabfold_models')
    shutil.copytree(models_src, models_dest, dirs_exist_ok=True)
    print(f'Added ColabFold models directory for {locus_tag}')
    models_merged_count += 1

for locus_tag, summary_file in summary_data:
    summary_src = Path(summary_file)
    if not summary_src.exists() or not summary_src.is_file():
        print(f'WARNING: summary file not found for {locus_tag} at {summary_file}')
        failed_count += 1
        continue

    locus_structure_dir = os.path.join(base_path, locus_tag)
    if os.path.islink(locus_structure_dir):
        source_dir = os.path.realpath(locus_structure_dir)
        os.unlink(locus_structure_dir)
        shutil.copytree(source_dir, locus_structure_dir, dirs_exist_ok=True)
    os.makedirs(locus_structure_dir, exist_ok=True)
    summary_dest = os.path.join(locus_structure_dir, summary_src.name)
    shutil.copy2(summary_src, summary_dest)
    print(f'Updated structure summary for {locus_tag}: {summary_src.name}')
    summary_merged_count += 1

processed_loci = len(set([x[0] for x in cb_data] + [x[0] for x in models_data] + [x[0] for x in summary_data]))
print(f'COLLECT: Processed loci: {processed_loci} | CB merged: {cb_merged_count} | models merged: {models_merged_count} | summaries merged: {summary_merged_count} | failed: {failed_count}')
print('Stage 2.5 COLLECT completed successfully')
"""

    stub:
    """
    mkdir -p ${organism_name}/structures/gene_example/colabfold_models
    touch ${organism_name}/structures/gene_example/CB_gene_example_unrelaxed1.pdb
    echo "STUB: ColabFold collect for ${organism_name}"
    """
}

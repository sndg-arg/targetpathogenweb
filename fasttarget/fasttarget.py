import os
import configuration
import pandas as pd
import argparse
import multiprocessing
from ftscripts import files, structures, pathways, offtargets, genome, essentiality, metadata
from datetime import datetime
import logging
import sys
from ftscripts.logger import logger 
import shutil

def print_stylized(title, width=80):
    """
    Print a stylized title to the console.
    """
    dash_line = '-' * width
    asterisk_line = '*' * width
    print(dash_line)
    print(f'{title.center(width)}')
    print(asterisk_line)

def prepare_genome_files(config, output_path):
    """
    Prepare genome files and organism subfolders.
    :param config: Configuration object.
    :param output_path: Path to the output directory.
    """

    # Organism data
    print_stylized('GENOME')

    organism_name = config.organism['name']
    tax_id = config.organism['tax_id']
    strain_taxid = config.organism['strain_taxid']
    gbk_file = config.organism['gbk_file']
    
    print(f'Organism name: {organism_name}')
    print(f'Species Tax ID: {tax_id}')
    print(f'Strain Tax ID: {strain_taxid}')
    print(f'Genome file: {gbk_file}')

    # Create organism subfolders
    files.create_organism_subfolders(output_path, organism_name)
    logging.info(f'Organism subfolders created in {output_path}/{organism_name}')

    # Create organism genome files (gbk, gff3 and fasta)
    files_dir = os.path.join(output_path, organism_name, 'genome')
    if not os.path.exists(files_dir):
        os.makedirs(files_dir, exist_ok=True)
        logging.info(f'Genome directory created in {files_dir}')
        
    genome.ref_genome_files(gbk_file, files_dir, organism_name, container_engine=config.container_engine)

    logging.info(f'Genome files created in {output_path}/{organism_name}')

def metabolic_module(config, output_path):
    """
    Run metabolic analysis based on configuration.
    :param config: Configuration object.
    :param output_path: Path to the output directory.
    :return: List of resulting DataFrames.
    """

    organism_name = config.organism['name']
    module_tables = []

    # Run METABOLIC ANALYSIS
    if config.metabolism_pathwaytools:
        try:
            print_stylized('Metabolic analysis - Pathway Tools')
            print('Using Pathway Tools output files')

            logging.info('Starting metabolic analysis')

            sbml_file =  config.metabolism_pathwaytools['sbml_file']
            chokepoint_file = config.metabolism_pathwaytools['chokepoint_file']
            smarttable_file = config.metabolism_pathwaytools['smarttable_file']
            curated_ubiquitous_file = config.metabolism_pathwaytools.get('curated_ubiquitous_file', None)
            
            # Handle empty string or None for curated_ubiquitous_file
            if curated_ubiquitous_file == "" or curated_ubiquitous_file is None:
                curated_ubiquitous_file = None

            logging.info(f'SBML file: {sbml_file}')
            logging.info(f'Chokepoint file: {chokepoint_file}')
            logging.info(f'Smarttable file: {smarttable_file}')
            if curated_ubiquitous_file:
                logging.info(f'Curated ubiquitous file: {curated_ubiquitous_file}')
            else:
                logging.info('Curated ubiquitous file: Not provided (will use auto-generated)')

            # Parse metabolic files, make network and calculate centrality
            df_centrality, df_edges, producing_df, consuming_df, both_df = pathways.run_metabolism_ptools (output_path, organism_name, sbml_file, chokepoint_file, smarttable_file, curated_ubiquitous_file)
            module_tables.append(df_centrality)
            module_tables.append(df_edges)
            module_tables.append(producing_df)
            module_tables.append(consuming_df)
            module_tables.append(both_df)

            logging.info('Metabolic analysis finished')

        except Exception as e:
            logging.exception(f'Error in metabolic analysis: {e}')        
    else:
        logging.info('Metabolic analysis with Pathway Tools files not enabled')
    

    if config.metabolism_sbml:
        try:
            print_stylized('Metabolic analysis - Custom SBML file')
            print('Using SBML file and MetaGraphTools')
            
            logging.info('Starting metabolic analysis')

            sbml_file =  config.metabolism_sbml['sbml_file']
            filter_file = config.metabolism_sbml.get('filter_file', None)
            
            # Handle empty string or None for filter_file
            if filter_file == "" or filter_file is None:
                filter_file = None

            logging.info(f'SBML file: {sbml_file}')
            if filter_file:
                logging.info(f'Filter file: {filter_file}')
            else:
                logging.info('Filter file: Not provided (will use default frequency filter)')

            # Parse metabolic files, make network and calculate centrality
            mgt_bc_df, mgt_degree_df, mgt_consumption_df, mgt_production_df = pathways.run_metabolism_sbml (output_path, organism_name, sbml_file, filter_file, container_engine=config.container_engine)

            module_tables.append(mgt_bc_df)
            module_tables.append(mgt_degree_df)
            module_tables.append(mgt_consumption_df)
            module_tables.append(mgt_production_df)

            logging.info('Metabolic analysis from SBML with MetaGraphTools finished')

        except Exception as e:
            logging.exception(f'Error in metabolic analysis: {e}')
    else:
        logging.info('Metabolic analysis with SBML file not enabled')
    
    return module_tables
    
def structure_module(config, databases_path, output_path, cpus):
    """
    Run structure analysis based on configuration.
    :param config: Configuration object.
    :param databases_path: Path to the databases directory.
    :param output_path: Path to the output directory.
    :param cpus: Number of CPUs to use.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    
    # Run STRUCTURES
    organism_name = config.organism['name']
    tax_id = config.organism['tax_id']
    strain_taxid = config.organism['strain_taxid']

    if config.structures:
        try:
            print_stylized('STRUCTURES')
            logging.info('Starting structures analysis')

            logging.info(f'Species Tax ID: {tax_id}')
            logging.info(f'Strain Tax ID: {strain_taxid}')

            pocket_full_mode = config.structures.get('pocket_full_mode', False)
            logging.info(f'Pocket full mode: {pocket_full_mode}')

            #Colabfold options
            amber_option = False
            gpu_option = False
            colabfold_all_models_option = False
            if config.colabfold:
                amber_option = config.colabfold.get('amber', False)
                gpu_option = config.colabfold.get('gpu', False)
                colabfold_all_models_option = config.colabfold.get('colabfold_run_all', False)
            logging.info(f'ColabFold Amber option: {amber_option}')
            logging.info(f'ColabFold GPU option: {gpu_option}')
            logging.info(f'ColabFold Run All Models option: {colabfold_all_models_option}')
            
            # Run complete structure pipeline: UniProt mapping, structure download, and pocket detection
            df_structures = structures.pipeline_structures(output_path, 
                                                            organism_name, 
                                                            tax_id, 
                                                            strain_taxid, 
                                                            cpus=cpus,
                                                            resolution_cutoff=3.5, 
                                                            coverage_cutoff=40.0,
                                                            container_engine=config.container_engine, 
                                                            full_mode=pocket_full_mode, 
                                                            amber_option=amber_option, 
                                                            gpu_option=gpu_option,
                                                            colabfold=config.colabfold,
                                                            colabfold_all_models=colabfold_all_models_option)
            logging.info('Structures analysis finished')
            module_tables.append(df_structures)

        except Exception as e:
            logging.exception(f'Error in structures analysis: {e}')
    else:
        logging.info('Structures analysis not enabled')
    
    return module_tables

def conservation_module(config, databases_path, output_path, cpus):
    """
    Run conservation analysis based on configuration.
    :param config: Configuration object.
    :param databases_path: Path to the databases directory.
    :param output_path: Path to the output directory.
    :param cpus: Number of CPUs to use.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    
    # Run CORE ANALYSIS
    organism_name = config.organism['name']
    tax_id = config.organism['tax_id']

    if config.core:
        try:
            print_stylized('CORE ANALYSIS')
            
            logging.info('Starting core analysis')

            # Read accession list if provided
            accession_list = None
            if config.core.get('accession_file'):
                accession_file = config.core['accession_file']
                if accession_file and accession_file != 'null' and os.path.exists(accession_file):
                    print(f'Reading accession list from: {accession_file}')
                    with open(accession_file, 'r') as f:
                        accession_list = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                    print(f'Found {len(accession_list)} accessions to download')
                    logging.info(f'Using accession list with {len(accession_list)} genomes')
                else:
                    logging.warning(f'Accession file not found or invalid: {accession_file}')

            # Download complete NCBI genomes from organism tax id or accession list
            if accession_list:
                print('----- 1. Downloading specific genomes from accession list -----')
            else:
                print('----- 1. Downloading tax_id genomes from NCBI -----')
            genome.core_download_genomes_ncbi(output_path, organism_name, tax_id, accession_list=accession_list)
            genome.core_download_missing_accessions(output_path, organism_name, tax_id, accession_list=accession_list)
            logging.info('Genomes downloaded')

            # Keep genomes with human as host. Check presence of .gff and .faa files for each strain
            print('----- 1. Selecting genomes -----')
            # If accession_list was provided, don't filter by host; otherwise filter for human host
            filter_by_host = accession_list is None or len(accession_list) == 0
            genome.core_check_files(output_path, organism_name, container_engine=config.container_engine, filter_by_host=filter_by_host)
            logging.info('Genomes filtered')
            print('----- 1. Finished -----')

            min_identity = config.core['min_identity']
            min_core_freq = config.core['min_core_freq']

            if config.core['roary']:
                try:
                    #Run roary
                    print('----- 2. Running Roary -----')
                    logging.info('Starting Roary analysis')
                    genome.core_genome_programs(output_path, organism_name, min_core_freq, min_identity, cpus, program_list=['roary'], container_engine=config.container_engine)
                    # Parse output
                    print('----- 2. Parsing Roary results -----')
                    df_roary = genome.roary_output(output_path, organism_name, core_threshold=min_core_freq/100)
                    module_tables.append(df_roary)
                    logging.info('Roary analysis finished')
                    print('----- 2. Finished -----')
                except Exception as e:
                    logging.exception(f'Error in Roary analysis: {e}')
            else:
                logging.info('Roary not enabled')

            if config.core['corecruncher']:
                try:
                    # Run CoreCruncher
                    print('----- 2. Running CoreCruncher -----')
                    logging.info('Starting CoreCruncher analysis')
                    genome.core_genome_programs(output_path, organism_name, min_core_freq, min_identity, cpus, program_list=['corecruncher'], container_engine=config.container_engine)
                    # Parse output
                    print('----- 2. Parsing CoreCruncher results -----')
                    df_cc = genome.corecruncher_output(output_path, organism_name)
                    module_tables.append(df_cc)
                    logging.info('CoreCruncher analysis finished')
                    print('----- 2. Finished -----')
                except Exception as e:
                    logging.exception(f'Error in CoreCruncher analysis: {e}')
            else:
                logging.info('CoreCruncher not enabled')
        except Exception as e:
            logging.exception(f'Error in core analysis: {e}')
    else:
        logging.info('Core analysis not enabled')
    
    return module_tables

def offtarget_module(config, databases_path, output_path, cpus):
    """
    Run offtarget analysis based on configuration.
    :param config: Configuration object.
    :param databases_path: Path to the databases directory.
    :param output_path: Path to the output directory.
    :param cpus: Number of CPUs to use.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    organism_name = config.organism['name']
    
    # Run OFFTARGETS
    if config.offtarget:
        try:
            offtarget_path = os.path.join(output_path, organism_name, 'offtarget')

            if config.offtarget['human']:
                try:
                    print_stylized('HUMAN OFFTARGET')

                    human_blast_output = os.path.join(offtarget_path, 'human_offtarget_blast.tsv')
                    
                    if not files.file_check(human_blast_output):
                        # Run blastp search
                        print('-----  Blastp search -----')
                        offtargets.human_offtarget_blast(databases_path, output_path, organism_name, cpus)
                        logging.info('Human offtarget blast search finished')
                    else:
                        logging.info('Blast with human already done')
                        print('Blast output file found')
                        print(human_blast_output)

                    # Parse results
                    df_human = offtargets.human_offtarget_parse(output_path, organism_name)
                    module_tables.append(df_human)
                    logging.info('Human offtarget analysis finished')
                    print('----- Finished -----')
                except Exception as e:
                    logging.exception(f'Error in human offtarget analysis: {e}')
            else:
                logging.info('Human offtarget analysis not enabled')

            if config.offtarget['microbiome']:
                try:

                    print_stylized('MICROBIOME OFFTARGET')

                    # Run blastp search
                    print('----- Blastp search -----')
                    offtargets.microbiome_offtarget_blast_species(databases_path, output_path, organism_name, cpus)
                    logging.info('Microbiome offtarget blast search finished')

                    # Parse results
                    microbiome_identity_filter = config.offtarget['microbiome_identity_filter']
                    microbiome_coverage_filter = config.offtarget['microbiome_coverage_filter']
                    logging.info(f'Microbiome identity filter: {microbiome_identity_filter}')
                    logging.info(f'Microbiome coverage filter: {microbiome_coverage_filter}')
                    df_microbiome_norm, df_microbiome_counts, df_microbiome_total_genomes = offtargets.microbiome_species_parse(databases_path, output_path, organism_name, microbiome_identity_filter, microbiome_coverage_filter)
                    module_tables.append(df_microbiome_norm)
                    module_tables.append(df_microbiome_counts)
                    module_tables.append(df_microbiome_total_genomes)
                    logging.info('Microbiome offtarget analysis finished')
                    print('----- Finished -----')
                            
                except Exception as e:
                    logging.exception(f'Error in microbiome offtarget analysis: {e}')
            else:
                logging.info('Microbiome offtarget analysis not enabled')
            
            if config.structures and config.offtarget['foldseek_human']:
                try:
                    print_stylized('FOLDSEEK HUMAN OFFTARGET')
                   
                    # Run foldseek against human structures
                    foldseek_mapping = offtargets.run_foldseek_human_structures (databases_path, output_path, organism_name, container_engine=config.container_engine)
                    logging.info('Foldseek human offtarget search finished')
                    
                    # Parse results
                    results_foldseek_dict = offtargets.foldseek_human_parser (output_path, organism_name, foldseek_mapping)
                    mapped_dict_foldseek = offtargets.merge_foldseek_data (output_path, organism_name)
                    final_foldseek_df = offtargets.final_foldseek_structure_table (output_path, organism_name, mapped_dict_foldseek)
                    module_tables.append(final_foldseek_df)

                    if config.colabfold and config.colabfold.get('colabfold_run_all', False):
                        foldseek_colab_mapping = offtargets.run_foldseek_human_colabfold_structures(
                            databases_path,
                            output_path,
                            organism_name,
                            container_engine=config.container_engine
                        )
                        logging.info('Foldseek human offtarget search for ColabFold structures finished')

                        results_foldseek_colab_dict = offtargets.foldseek_human_colabfold_parser(
                            output_path,
                            organism_name,
                            foldseek_colab_mapping
                        )
                        mapped_dict_foldseek_colab = offtargets.merge_foldseek_colabfold_data(
                            output_path,
                            organism_name
                        )
                        final_foldseek_colab_df = offtargets.final_foldseek_colabfold_structure_table(
                            output_path,
                            organism_name,
                            mapped_dict_foldseek_colab
                        )
                        module_tables.append(final_foldseek_colab_df)

                    logging.info('Foldseek human offtarget analysis finished')
                    print('----- Finished -----')
                except Exception as e:
                    logging.exception(f'Error in foldseek human offtarget analysis: {e}')
            else:
                logging.info('Foldseek human offtarget analysis not enabled')           

        except Exception as e:
            logging.exception(f'Error in offtarget analysis: {e}')
    else:
        logging.info('Offtarget analysis not enabled')
    
    return module_tables

def essentiality_module(config, databases_path, output_path, cpus):
    """
    Run essentiality analysis based on configuration.
    :param config: Configuration object.
    :param databases_path: Path to the databases directory.
    :param output_path: Path to the output directory.
    :param cpus: Number of CPUs to use.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    organism_name = config.organism['name']

    # Run ESSENTIALITY
    if config.deg:
        essentiality_path = os.path.join(output_path, organism_name, 'essentiality')
        try:
            print_stylized('ESSENTIALITY')

            deg_blast_output = os.path.join(essentiality_path, 'deg_blast.tsv')
            
            if not files.file_check(deg_blast_output):
                # Run blastp search
                print('----- Blastp search -----')
                essentiality.essential_deg_blast(databases_path, output_path, organism_name, cpus)
                logging.info('DEG blast search finished')
            else:
                logging.info('Blast with DEG already done')
                print('Blast output file found')
                print(deg_blast_output)      

            # Parse results
            deg_identity_filter = config.deg['deg_identity_filter']
            deg_coverage_filter = config.deg['deg_coverage_filter']
            logging.info(f'DEG identity filter: {deg_identity_filter}')
            logging.info(f'DEG coverage filter: {deg_coverage_filter}')
            df_deg = essentiality.deg_parse(output_path, organism_name, deg_identity_filter, deg_coverage_filter)
            module_tables.append(df_deg)
            logging.info('DEG analysis finished')
            print('----- Finished -----')

        except Exception as e:
            logging.exception(f'Error in essentiality analysis: {e}')
    else:
        logging.info('Essentiality analysis not enabled')
    
    return module_tables

def localization_module(config, output_path):
    """
    Run localization analysis based on configuration.
    :param config: Configuration object.
    :param output_path: Path to the output directory.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    organism_name = config.organism['name']
    # Run LOCALIZATION
    if config.psortb:
        try:
            print_stylized('LOCALIZATION')

            gram_type = config.psortb['gram_type']
            logging.info(f'Gram type: {gram_type}')
            
            #Run psortb
            print('----- Running psort -----')
            df_psort = genome.localization_prediction(output_path, organism_name, gram_type, container_engine=config.container_engine)
            module_tables.append(df_psort)
            logging.info('Psortb analysis finished')
            print('----- Finished -----')
        except Exception as e:
            logging.exception(f'Error in localization analysis: {e}')
    else:
        logging.info('Localization analysis not enabled')
    
    return module_tables

def metadata_loading(config, output_path):
    """
    Load metadata tables based on configuration.
    :param config: Configuration object.
    :param output_path: Path to the output directory.
    :return: List of resulting DataFrames.
    """

    module_tables = []
    organism_name = config.organism['name']

    # Load METADATA
    if config.metadata:
        try:
            print_stylized('METADATA')
            for table in config.metadata['meta_tables']:
                print(f'----- Loading metadata table: {table} -----')
                shutil.copy(table, os.path.join(output_path, organism_name, 'metadata'))
                with open(table, 'r') as file:
                    first_line = file.readline()
                    if '\t' in first_line:
                        sep = '\t'
                    elif ',' in first_line:
                        sep = ','
                    elif ';' in first_line:
                        sep = ';'
                    else:
                        raise ValueError('Invalid file format. Only CSV and TSV metadata files are supported.')

                df_meta = pd.read_csv(table, header=0, sep=sep)
                module_tables.append(df_meta)
                logging.info(f'Metadata table {table} loaded')
                print('----- Finished -----')
        except Exception as e:
            logging.exception(f'Error in metadata analysis: {e}')
    else:
        logging.info('Metadata analysis not enabled')
    
    return module_tables

def merge_final_tables(config, output_path, tables):
    """
    Merge final result tables and save to output.
    :param config: Configuration object.
    :param output_path: Path to the output directory.
    :param tables: List of DataFrames to merge.
    :return: Combined DataFrame with results.
    """

    organism_name = config.organism['name']

    # Merge dfs
    print_stylized('RESULTS')
    current_date = datetime.now().strftime('%Y-%m-%d-%H-%M')
    results_path = os.path.join(output_path, organism_name, f'{organism_name}_results_{current_date}')
    results_table_path = os.path.join(results_path, f'{organism_name}_results_table.tsv')

    if not os.path.exists(results_path):
        os.makedirs(results_path, exist_ok=True)
        logging.info(f'Results directory created in {results_path}')
    

    if len(tables) > 1:
        combined_df = tables[0]
        for df in tables[1:]:
            if df is not None:
                combined_df = pd.merge(combined_df, df, on='gene', how='left')
        
        # Add gene_name and product information
        combined_df = metadata.add_gene_product_info(combined_df, output_path, organism_name)
        
        combined_df.to_csv(results_table_path, sep='\t', index=False)
        
        print(f'Final FastTarget results saved in {results_table_path}.')
        logging.info(f'Final FastTarget results saved.')
        
        results = combined_df

        # Create metadata tables for Target Pathogen
        print('\n')
        print('Creating metadata tables for Target Pathogen')
        metadata.tables_for_TP(organism_name, results_path)
        logging.info('Tables for Target Pathogen created')

    elif len(tables) == 1:
        tables[0] = metadata.add_gene_product_info(tables[0], output_path, organism_name)
        tables[0].to_csv(results_table_path, sep='\t', index=False)
        print(f'Final FastTarget results saved in {results_table_path}.')
        logging.info(f'Final FastTarget results saved.')
        results = tables[0]

        # Create metadata tables for Target Pathogen
        print('\n')
        print('Creating metadata tables for Target Pathogen')
        metadata.tables_for_TP(organism_name, results_path)
        logging.info('Tables for Target Pathogen created')
    else:
        logging.error('----- Error: No final DataFrame data. -----')
        results = None
    
    return results

def main(config, databases_path, output_path):
    """
    Main function to run FastTarget.
    
    :param config: Configuration object.
    :param databases_path: Path to the databases directory.
    :param output_path: Path to the output directory.

    :return: DataFrame with the results.
    """
    results = None

    # Prepare genome files
    prepare_genome_files(config, output_path)
    
    # Number of CPUS
    if isinstance(config.cpus, int):
        cpus = config.cpus
    else:
        cpus = multiprocessing.cpu_count()

    logging.info(f'CPUS: {cpus}')

    tables = []

    error_modules = []

    # Run metabolic module
    try:
        logging.info('Starting metabolic module')
        metabolic_tables = metabolic_module(config, output_path)
        if metabolic_tables:
            tables.extend(metabolic_tables)
            logging.info(f'Metabolic module completed - {len(metabolic_tables)} table(s) generated')
        else:
            logging.info('Metabolic module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in metabolic module: {e}')
        error_modules.append('metabolic')
        print(f'Warning: Metabolic module failed - {e}')

    # Run structure module
    try:
        logging.info('Starting structure module')
        structure_tables = structure_module(config, databases_path, output_path, cpus)
        if structure_tables:
            tables.extend(structure_tables)
            logging.info(f'Structure module completed - {len(structure_tables)} table(s) generated')
        else:
            logging.info('Structure module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in structure module: {e}')
        error_modules.append('structure')
        print(f'Warning: Structure module failed - {e}')

    # Run conservation module
    try:
        logging.info('Starting conservation module')
        conservation_tables = conservation_module(config, databases_path, output_path, cpus)
        if conservation_tables:
            tables.extend(conservation_tables)
            logging.info(f'Conservation module completed - {len(conservation_tables)} table(s) generated')
        else:
            logging.info('Conservation module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in conservation module: {e}')
        error_modules.append('conservation')
        print(f'Warning: Conservation module failed - {e}')

    # Run offtarget module
    try:
        logging.info('Starting offtarget module')
        offtarget_tables = offtarget_module(config, databases_path, output_path, cpus)
        if offtarget_tables:
            tables.extend(offtarget_tables)
            logging.info(f'Offtarget module completed - {len(offtarget_tables)} table(s) generated')
        else:
            logging.info('Offtarget module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in offtarget module: {e}')
        error_modules.append('offtarget')
        print(f'Warning: Offtarget module failed - {e}')

    # Run essentiality module
    try:
        logging.info('Starting essentiality module')
        essentiality_tables = essentiality_module(config, databases_path, output_path, cpus)
        if essentiality_tables:
            tables.extend(essentiality_tables)
            logging.info(f'Essentiality module completed - {len(essentiality_tables)} table(s) generated')
        else:
            logging.info('Essentiality module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in essentiality module: {e}')
        error_modules.append('essentiality')
        print(f'Warning: Essentiality module failed - {e}')

    # Run localization module
    try:
        logging.info('Starting localization module')
        localization_tables = localization_module(config, output_path)
        if localization_tables:
            tables.extend(localization_tables)
            logging.info(f'Localization module completed - {len(localization_tables)} table(s) generated')
        else:
            logging.info('Localization module completed - no tables generated')
    except Exception as e:
        logging.exception(f'Fatal error in localization module: {e}')
        error_modules.append('localization')
        print(f'Warning: Localization module failed - {e}')

    # Load metadata
    try:
        logging.info('Starting metadata loading')
        metadata_tables = metadata_loading(config, output_path)
        if metadata_tables:
            tables.extend(metadata_tables)
            logging.info(f'Metadata loading completed - {len(metadata_tables)} table(s) loaded')
        else:
            logging.info('Metadata loading completed - no tables loaded')
    except Exception as e:
        logging.exception(f'Fatal error in metadata loading: {e}')
        error_modules.append('metadata')
        print(f'Warning: Metadata loading failed - {e}')

    # Merge final tables
    logging.info(f'Total tables collected: {len(tables)}')
    if error_modules:
        logging.info(f'Modules with errors: {", ".join(error_modules)}')

    results = merge_final_tables(config, output_path, tables)
    

    print('------------------------------------- FINISHED ----------------------------------------')
    
    return results 

if __name__ == "__main__":
    
    base_path = os.path.dirname(os.path.abspath(__file__))

    databases_default_path = os.path.join(base_path, 'databases')
    output_default_path = os.path.join(base_path, 'organism')

    parser = argparse.ArgumentParser(description='FastTarget script')
    parser.add_argument('--config_file', type=str, default='config.yml', help='Path to the configuration file')
    parser.add_argument('--databases_path', type=str, default=databases_default_path, help='Path to the databases directory')
    parser.add_argument('--output_path', type=str, default=output_default_path, help='Path to the output directory')
    
    args = parser.parse_args()

    config = configuration.get_config(args.config_file)
    

    main(config, args.databases_path, args.output_path)

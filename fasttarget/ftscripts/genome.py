from Bio import SeqIO
from Bio.SeqFeature import SeqFeature, FeatureLocation, ExactPosition
import os
import shutil
import tqdm
from ftscripts import programs, metadata, files
import multiprocessing
import glob
import csv
import pandas as pd
from BCBio import GFF
import sys
import subprocess
import logging


def gbk_to_gff3(gbk_file, gff_dir):

    """
    Convert a GenBank file to GFF3 format.

    This function converts a GenBank file to GFF3 format and saves the output to a file in the specified directory.

    :param gbk_file: GenBank file path.
    :param gff_dir: Directory where the GFF3 file will be saved.
    """

    def fix_genbank_file(input_file, output_file):
        """
        Fix a GenBank file to be compatible with GFF3 format.

        This function fixes a GenBank file to be compatible with GFF3 format.
        It removes invalid characters from the location and codon_start fields.
        It also changes the type of features in pseudogenes.

        :param input_file: Input GenBank file path.
        :param output_file: Output GenBank file path.
        """

        
        fixed_records = []
        with open(input_file, "r") as in_handle, open(output_file, "w") as out_handle:
            for record in SeqIO.parse(in_handle, "genbank"):
                for feature in record.features:
                    if 'pseudo' in feature.qualifiers:
                        if feature.type == "gene":
                            feature.type = 'pseudogenic'
                        if feature.type == "CDS":
                            feature.type = 'pseudogene'
                    if feature.location:
                        # Clean the location by recreating the FeatureLocation object
                        start_pos = ExactPosition(int(str(feature.location.start).replace("<","").replace(">","")))
                        end_pos = ExactPosition(int(str(feature.location.end).replace("<","").replace(">","")))
                        cleaned_location = FeatureLocation(start_pos, end_pos, feature.location.strand)
                        feature.location = cleaned_location
                    if "codon_start" in feature.qualifiers:
                        try:
                            # Attempt to convert codon_start to an integer
                            int(feature.qualifiers["codon_start"][0])
                        except ValueError:
                            # Replace invalid codon_start with default value (1)
                            feature.qualifiers["codon_start"][0] = "1"
                fixed_records.append(record)

            SeqIO.write(fixed_records, out_handle, "genbank")
            print(f"Fixed GenBank file saved to {output_file}")

    def write_gff3(gff_file, gb_records):
        """
        Write a list of GenBank records to a GFF3 file.

        :param gff_file: Output GFF3 file path.
        :param gb_records: List of GenBank records.

        """
        with open(gff_file, "w") as output_handle:
            GFF.write(gb_records, output_handle)

            # Add FASTA sequence at the end of the GFF file
            output_handle.write("##FASTA\n")
            for gb_record in gb_records:
                
                output_handle.write(f">{gb_record.id}\n")
                output_handle.write(str(gb_record.seq) + "\n")
                
                # Add CDS sequences
                for feature in gb_record.features:
                    if feature.type == "CDS":
                        if 'translation' in feature.qualifiers:
                            #cds_id = feature.qualifiers['locus_tag'][0]
                            cds_seq = feature.qualifiers['translation'][0]
                            cds_id = feature.qualifiers.get("locus_tag", ["unknown"])[0]

                            output_handle.write(f">{cds_id}.p01\n")
                            output_handle.write(str(cds_seq) + "\n")
        print(f"GFF3 file saved to {gff_file}")

    if os.path.exists(gff_dir):
        # Fix: Remove .gbk extension before adding .gff
        base_name = os.path.splitext(os.path.basename(gbk_file))[0]
        gff_file = os.path.join(gff_dir, f'{base_name}.gff')
        if os.path.exists(gbk_file):
            try: 
                fixed_gbk = os.path.join(os.path.dirname(gbk_file), f'fix_{os.path.basename(gbk_file)}')
                fix_genbank_file(gbk_file, fixed_gbk)
                records = []
                with open(fixed_gbk) as input_handle:
                    for gb_record in SeqIO.parse(input_handle, "genbank"):
                        records.append(gb_record)

                write_gff3(gff_file, records)
            except Exception as e:
                logging.exception(f"An error occurred during GBK to GFF3 conversion: {e}")
                raise  # Re-raise to let caller know it failed
        else:
            logging.error(f"GBK file '{gbk_file}' not found.")
    else:
        logging.error(f"Gff dir '{gff_dir}' not found.")

def add_sequences_to_gff3(gff_file, gbk_file):
    """
    Add genome and protein sequences to a GFF3 file.

    :param gff_file: GFF3 file path.
    :param gbk_file: GenBank file path.    
    """

    with open(gbk_file, "r") as gbk_handle, open(gff_file, "a") as output_handle:
        # Parse the GenBank file
        gb_records = SeqIO.parse(gbk_handle, "genbank")
        
        # Add the FASTA section header
        output_handle.write("##FASTA\n")
        
        # Iterate over each record and append genome and protein sequences
        for gb_record in gb_records:
            # Append genome sequence
            output_handle.write(f">{gb_record.id}\n")
            output_handle.write(str(gb_record.seq) + "\n")
            
            # Append protein sequences from CDS features
            for feature in gb_record.features:
                if feature.type == "CDS" and 'translation' in feature.qualifiers:
                    cds_id = feature.qualifiers.get("locus_tag", ["unknown"])[0]
                    cds_seq = feature.qualifiers['translation'][0]
                    output_handle.write(f">{cds_id}.p01\n")
                    output_handle.write(str(cds_seq) + "\n")
    
    print(f"Genome and protein sequences added to {gff_file}")

def gbk_locus_strain_host(gbk_file):
    """
    Extracts the locus tag, strain, and host from a GenBank file.

    :param gbk_file: GenBank file path.
    
    :return: Locus tag list, strain, and host.
    """
    
    locus_tag_list = []
    strain = None
    host = None
    for record in SeqIO.parse(gbk_file, "genbank"):
        locus_tag = record.name
        locus_tag_list.append(locus_tag)
        print(locus_tag)
        for feature in record.features:
            if feature.type == "source":
                strain = feature.qualifiers.get("strain", ["unknown"])[0]
                strain = strain.replace(" ", "_")
                strain = strain.replace("/", "_")
                strain = strain.replace("(", "_")
                strain = strain.replace(")", "_")
                strain = strain.replace(":", "_")
                strain = strain.replace(";", "_")

                if 'host' in feature.qualifiers:
                    host = feature.qualifiers['host'][0]

    return locus_tag_list, strain, host

def gbk_to_fasta(gbk_file, output_file_fna=None, output_file_faa=None, output_file_ffn=None):
    """
    Generates the .faa, .fna, and/or .ffn files for a GenBank file.

    :param gbk_file: GenBank file path.
    :param output_file_fna: Output fna file path or None to skip.
    :param output_file_faa: Output faa file path or None to skip.
    :param output_file_ffn: Output ffn file path or None to skip.
    """

    protein_records = []
    nucleotide_records = []

    def split_sequence(seq, chunk_size=60):
        return [seq[i:i+chunk_size] for i in range(0, len(seq), chunk_size)]

    for record in SeqIO.parse(gbk_file, "genbank"):
        if output_file_fna:
            SeqIO.write(record, output_file_fna, "fasta")

        for feature in record.features:
            if feature.type == "CDS":
                if 'translation' in feature.qualifiers:
                    locus_tag = feature.qualifiers['locus_tag'][0]
                    header = f">{locus_tag}"

                    # Protein
                    protein_seq = feature.qualifiers['translation'][0]
                    protein_records.append(f"{header}\n" + "\n".join(split_sequence(protein_seq)))

                    # Nucleotide
                    nucleotide_seq = str(feature.extract(record.seq))
                    nucleotide_records.append(f"{header}\n" + "\n".join(split_sequence(nucleotide_seq)))

    if output_file_faa:
        with open(output_file_faa, 'w') as faa:
            faa.write("\n".join(protein_records))

    if output_file_ffn:
        with open(output_file_ffn, 'w') as ffn:
            ffn.write("\n".join(nucleotide_records))

def ref_genome_files (gbk_file, output_path, organism_name, container_engine='docker'):

    """
    Generates the .fna, .faa, .ffn, and .gff3 files for a reference GenBank file.

    :param gbk_file: GenBank file path.
    :param output_path: Directory where files will be saved.
    :param organism_name: Name of the organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').

    """

    ref_gbk = os.path.join(output_path, f'{organism_name}.gbk')

    if os.path.exists(gbk_file):
        shutil.copy(gbk_file, ref_gbk)
        print(f'GenBank file saved to {output_path}')
    else:
        print('Gbk file not found.')

    if os.path.exists(ref_gbk):
        output_file_fna_path = os.path.join(output_path, f'{organism_name}.fna')
        output_file_faa_path = os.path.join(output_path, f'{organism_name}.faa')
        output_file_ffn_path = os.path.join(output_path, f'{organism_name}.ffn')
        output_file_gff_path = os.path.join(output_path, f'{organism_name}.gff')

        if not files.file_check(output_file_fna_path) or not files.file_check(output_file_faa_path) or not files.file_check(output_file_ffn_path):
            gbk_to_fasta(ref_gbk, output_file_fna=output_file_fna_path, output_file_faa=output_file_faa_path, output_file_ffn=output_file_ffn_path)
            print(f'fna, faa and ffn files saved to {output_path}')
        else:
            print(f'fna, faa and ffn files already exist in {output_path}')

        if not files.file_check(output_file_gff_path):
            try:
                programs.run_genbank2gff3(ref_gbk, output_path, container_engine=container_engine)
                if os.path.exists(output_file_gff_path):
                    print(f'Gff3 file saved in {output_path}')
                else:
                    raise FileNotFoundError(f"Container succeeded but GFF file not found")
                    
            except Exception as e:
                logging.warning(f"Container method failed, trying Python fallback: {e}")
                try:
                    gbk_to_gff3(ref_gbk, output_path)
                    if os.path.exists(output_file_gff_path):
                        print(f'Gff3 file saved using Python fallback in {output_path}')
                    else:
                        logging.error(f"GFF file was not created at {output_file_gff_path}")
                        print(f'WARNING: GFF file could not be created. Some features may not work.')
                except Exception as e2:
                    logging.exception(f"Python fallback also failed: {e2}")
                    print(f'WARNING: GFF file could not be created. Some features may not work.')
        else:
            print(f'Gff3 file already exists in {output_path}')  

    else:
        print('Reference Gbk file not found.')
    
def id_to_locustag_gff(file_path:str, ids, fix=False):
    """

    Parses a .gff file, from a list of IDs retrieves a dictionary with the locus_tag for each ID.

    :param file_path: Path to the gff file.
    :param ids: List of IDs.
    :param fix: If True, work with IDs of roary index.

    :return: Dictionary with the locus_tag for each ID.

    """
    locus_tags = {}
    with open(file_path, 'r') as file:
        for rec in GFF.parse(file):
            for feature in rec.features:
                if 'ID' in feature.qualifiers:
                    feature_id = feature.qualifiers['ID'][0]
                    for id in ids:
                        if fix:
                            if feature_id == id and feature_id not in locus_tags:
                                locus_tags[feature_id] = feature.qualifiers.get('locus_tag', [feature_id])[0]
                        else:
                            if feature_id in id and feature_id not in locus_tags:
                                locus_tags[feature_id] = feature.qualifiers.get('locus_tag', [feature_id])[0]
    
    list_locus = list(locus_tags.values())
    return list_locus

def core_download_genomes_ncbi(output_path, organism_name, tax_id, accession_list=None):
    """
    Download genomes from NCBI.
    Can download either by taxonomy ID (all genomes) or from a specific list of accessions.
    This function uses the `run_ncbi_datasets` or `run_ncbi_datasets_accessions` function from the `programs` module.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param tax_id: Taxonomy ID from ncbi.
    :param accession_list: Optional list of specific assembly accessions to download. If provided, only these genomes will be downloaded.
    """

    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    
    if accession_list and len(accession_list) > 0:
        print(f'Downloading {len(accession_list)} specific genomes from accession list')
        programs.run_ncbi_datasets_accessions(accession_list, organism_name, conservation_dir)
    else:
        print(f'Downloading all genomes from taxonomy ID: {tax_id}')
        programs.run_ncbi_datasets(tax_id, organism_name, conservation_dir)

def core_check_genomes_ncbi(output_path, organism_name):
    """

    Check genomes downloaded from NCBI. 
    Parse assembly_data_report.jsonl and look for .gbff and .gff files not downloaded.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.

    :return: List of missing genomes.
    """

    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    ncbi_download_data = os.path.join(conservation_dir, f'{organism_name}_dataset', 'ncbi_dataset', 'data')

    assembly_json = os.path.join(ncbi_download_data,'assembly_data_report.jsonl')
    assembly_dict = files.jsonl_to_dict(assembly_json)

    required_files = ['*.gbff', '*.gff']
    all_accessions = []
    missing_files_accessions = []

    for item in assembly_dict:
        accession = item['accession']
        all_accessions.append(accession)
        
        accession_dir = os.path.join(ncbi_download_data, accession)
        
        for acc in required_files:
            if os.path.exists(accession_dir):
                files_gff = glob.glob(os.path.join(accession_dir, acc))
                if files_gff:
                    print(f'{acc} file found for {accession}')
                else:
                    missing_files_accessions.append(accession)
                    print(f'{acc} file from {accession} is missing.')
            else:
                missing_files_accessions.append(accession)
                print(f'{accession} is missing.')

    if len(missing_files_accessions) == 0:
        print(f'All genomes downloaded correctly.')
    else:
        print(f'Missing genomes: {missing_files_accessions}.')

    return missing_files_accessions
        
def core_download_missing_accessions(output_path, organism_name, tax_id, accession_list=None):
    """
    Check for missing genome files and download them if necessary.

    This function checks if there are any missing genome files for the given organism.
    If there are missing files, it attempts to download them from NCBI.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param tax_id: Taxonomy ID of the organism.
    :param accession_list: Optional list of specific assembly accessions. If provided, only these genomes are expected.
    """

    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    ncbi_download_data = os.path.join(conservation_dir, f'{organism_name}_dataset', 'ncbi_dataset', 'data')
    checkpoint_file =  os.path.join(ncbi_download_data, f'{organism_name}_checkpoint_check_datasets.txt')

    if not files.file_check(checkpoint_file):
        # Check for missing genome files
        missing_files_accessions = core_check_genomes_ncbi(output_path, organism_name)
        if len(missing_files_accessions) > 0:
            # Download missing genome files
            core_download_genomes_ncbi(output_path, organism_name, tax_id, accession_list=accession_list)

        # Re-check for missing genome files after download attempt
        missing_files_accessions = core_check_genomes_ncbi(output_path, organism_name)
        if len(missing_files_accessions) > 0:
            print(f'Missing genomes: {missing_files_accessions}.')
            print(len(missing_files_accessions)) 
            # Uncomment the following lines to download each missing accession
            # for accession in missing_files_accessions:
            #     programs.run_ncbi_accession(accession, ncbi_download_data)
            #     print(f'{accession} downloaded.')
        
        with open(checkpoint_file, 'w') as f:
            f.write("Check core genomes complete. Missing genomes:"+ str(set(missing_files_accessions)))
            f.close()
    else:
        print('Check already performed.')

def core_files(output_path, organism_name, container_engine='docker', filter_by_host=True):
    """
    Select genomes for core genome analysis and generate .faa and .gff3 files.

    This function processes the genomes of the given organism.
    If filter_by_host=True, it selects only those with Human as host.
    If filter_by_host=False, it includes all genomes that don't duplicate loci or strain.
    It generates the necessary .faa and .gff3 files for each genome.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param filter_by_host: If True, filter by 'Homo sapiens' host. If False, use all genomes.

    :return: List of core genomes IDs.
    """

    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    ncbi_download_data = os.path.join(conservation_dir, f'{organism_name}_dataset', 'ncbi_dataset', 'data')
           
    #Output directory for Roary, for input takes gff files
    gff_dir = os.path.join(conservation_dir, 'roary_output','gff')
    os.makedirs(gff_dir, exist_ok=True)
    #Output directory for CoreCruncher, for input takes faa files
    fasta_dir = os.path.join(conservation_dir, 'corecruncher_output','faa')
    os.makedirs(fasta_dir, exist_ok=True)
    
    print('Conservation gff and faa folders created.')
    core_genomes = [organism_name]

    #Reference genome
    ref_gbk = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.gbk')
    ref_gff = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.gff')
    ref_faa = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.faa')

    if not os.path.exists(os.path.join(gff_dir, f'{organism_name}.gff')):
        shutil.copy(ref_gff, gff_dir)
    if not os.path.exists(os.path.join(fasta_dir, f'{organism_name}.faa')):
        shutil.copy(ref_faa, fasta_dir)

    ref_locus_list, ref_strain, ref_host = gbk_locus_strain_host(ref_gbk)

    #Core genomes from NCBI
    for root, dirs, files_names in os.walk(ncbi_download_data):
        for i, dir_name in enumerate(dirs):
            assembly_id = str(dir_name).split(".")[0]

            print(f'Genome {i} from {len(dirs)}: {dir_name}')
            gbff_pattern = os.path.join(root, dir_name, "*.gbff")
            gbff_files = glob.glob(gbff_pattern)
            gbk_pattern = os.path.join(root, dir_name, "*.gbk")
            gbk_files = glob.glob(gbk_pattern)
            genome_files = gbff_files if len(gbff_files) == 1 else gbk_files

            gff_pattern = os.path.join(root, dir_name, "*.gff")
            gff_files = glob.glob(gff_pattern)
    
            if len(genome_files) == 1:

                locus_list, strain, host = gbk_locus_strain_host(genome_files[0])

                # Check if genome should be included based on filtering criteria
                include_genome = not set(locus_list) & set(ref_locus_list) and strain != ref_strain
                
                if filter_by_host and include_genome:
                    # When filtering by host, only include 'Homo sapiens'
                    include_genome = host == 'Homo sapiens'
                    if not include_genome:
                        print(f'{dir_name}: Host not Human: {host}, for {assembly_id}, {locus_list}, strain {strain}.')
                
                if include_genome:
                    core_genomes.append(f'{assembly_id}')  
                    
                    new_gbk = os.path.join(root, dir_name, f'{assembly_id}.gbk')
                    new_faa = os.path.join(fasta_dir, f'{assembly_id}.faa')
                    new_gff = os.path.join(gff_dir, f'{assembly_id}.gff')

                    if not os.path.exists(new_gbk):
                        if len(gbff_files) == 1:
                            shutil.move(gbff_files[0], new_gbk)
                        else:
                            shutil.copy(genome_files[0], new_gbk)
                    else:
                        print(f'{new_gbk} already exists.')

                    if not os.path.exists(new_faa):
                        gbk_to_fasta(new_gbk, output_file_faa=new_faa)
                    else:
                        print(f'{new_faa} already exists.')

                    if not os.path.exists(new_gff):
                        try:      
                            programs.run_genbank2gff3(new_gbk, gff_dir, container_engine=container_engine)
                            print(f"Processed {assembly_id}.gff")
                        except Exception as e:
                            logging.exception(f"Error in run_genbank2gff3: {e}")
                            if len(gff_files) == 1:
                                add_sequences_to_gff3(gff_files[0], new_gbk)
                                shutil.copy(gff_files[0], new_gff)
                                print(f"Processed {assembly_id}.gff")
                            else:
                                logging.error(
                                    f"Expected exactly one GFF fallback file for {assembly_id}, found {len(gff_files)}."
                                )
                    else:
                        print(f"{assembly_id}.gff already exists.")
                        shutil.rmtree(os.path.join(root, dir_name))
                else:
                    shutil.rmtree(os.path.join(root, dir_name))
            elif len(gbff_files) == 0 and len(gbk_files) == 0:
                logging.error(f"No .gbff or .gbk file found for {assembly_id} in {os.path.join(root, dir_name)}")
            else:
                print(f'More than one genome files.')

    print("Files processed successfully.")
    files.list_to_file(os.path.join(conservation_dir, 'core_genomes_IDs.txt'), core_genomes)
        
    return core_genomes


def core_check_files(output_path, organism_name, container_engine='docker', filter_by_host=True):
    """

    Check for missing files in the core genomes analysis.

    This function checks if the necessary files for the core genomes analysis are present.
    It checks for the presence of the .gff and .faa files.
    If pending files are found, it runs the `core_files` function to generate the missing files.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param filter_by_host: If True, filter genomes by 'Homo sapiens' host. If False, use all genomes.

    """
    conservation_dir = os.path.join(output_path, organism_name, 'conservation')  
    genomes_file = os.path.join(conservation_dir,'core_genomes_IDs.txt')
    fasta_dir = os.path.join(conservation_dir, 'corecruncher_output','faa')
    gff_dir = os.path.join(conservation_dir, 'roary_output','gff')

    def pending_files(genomes_list):
        
        pending_files = []

        for genome in tqdm.tqdm(genomes_list, initial=1):
            gff_file = os.path.join(gff_dir, f"{genome}.gff")
            faa_files = os.path.join(fasta_dir, f"{genome}.faa")

            if not os.path.exists(gff_file):
                pending_files.append(gff_file)
                print(f'{gff_file} not found.')

            if not os.path.exists(faa_files):
                pending_files.append(faa_files)
                print(f'{faa_files} not found.')
        
        if len(pending_files) == 0:
            print('All core files correct.')
        else:
            print('Error: Some core files are missing.')
            print(f'Number of pending files: {len(pending_files)}')
        
        return pending_files

    if files.file_check(genomes_file):
        genomes_list = files.file_to_list(genomes_file)
        pending_files = pending_files(genomes_list)
        if len(pending_files) > 0:
            core_files(output_path, organism_name, container_engine=container_engine, filter_by_host=filter_by_host)
    else:
        core_files(output_path, organism_name, container_engine=container_engine, filter_by_host=filter_by_host)
        if files.file_check(genomes_file):
            genomes_list = files.file_to_list(genomes_file)
            pending_files = pending_files(genomes_list)
            if len(pending_files) > 0:
                core_files(output_path, organism_name, container_engine=container_engine, filter_by_host=filter_by_host)
        else:
            print(f'No core genomes file found or empty: {genomes_file}.')

    return pending_files

def core_genome_programs(output_path, organism_name, core_threshold=99, identity=95, cpus=multiprocessing.cpu_count(), program_list=['roary','corecruncher'], container_engine='docker'):

    """
    Run Roary and CoreCruncher programs for the core genomes analysis of the given organism.

    This function runs Roary and CoreCruncher programs for the core genomes of the given organism to identify the core genes.
    It generates the necessary input files and runs the programs.

    This function uses the `run_roary` and `run_core_cruncher` functions from the `programs` module.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param cpus: Number of CPUs to use.
    :param program_list: List of programs to run, can be 'roary', 'corecruncher', or both.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    
    """

    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    gff_dir = os.path.join(conservation_dir, 'roary_output','gff')
    fasta_dir = os.path.join(conservation_dir, 'corecruncher_output','faa')

    if 'roary' in program_list:
        roary_out_dir = os.path.join(conservation_dir, 'roary_output')
        results_dir = os.path.join(roary_out_dir, 'results')
        genes_csv_file = os.path.join(results_dir, 'gene_presence_absence.csv')
        if os.path.exists(gff_dir):
            if not files.file_check(genes_csv_file):
                print('Running Roary')
                programs.run_roary(roary_out_dir, gff_dir, results_dir, core_threshold=99, identity=95, cpus=cpus, container_engine=container_engine)
                print('Finished')
            else:
                print(f'Roary output file already exists: {genes_csv_file}.')
        else:
            print(f'{gff_dir} not found.')

    if 'corecruncher' in program_list:
        ccruncher_out_dir = os.path.join(conservation_dir, 'corecruncher_output')
        cc_output_file = os.path.join(ccruncher_out_dir, 'families_core.txt')
        
        if os.path.exists(fasta_dir):
            if not files.file_check(cc_output_file):
                reference_file = f'{organism_name}.faa'
                print('Running CoreCruncher')
                programs.run_core_cruncher(ccruncher_out_dir, reference_file, core_threshold=99, identity=95, container_engine=container_engine)
                print('Finished')
            else:
                print(f'CoreCruncher output file already exists: {cc_output_file}.')
        else:
            print(f'{fasta_dir} not found.')

def roary_output(output_path, organism_name, core_threshold=0.99):
    """    
    This function processes the output files generated by Roary for the specified organism.
    It reads the 'gene_presence_absence.csv' file to extract the core locus tags and generates a metadata table with these IDs.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :core_threshold: Threshold to consider a gene as core (default is 0.99 for 99%).
    
    :return: A list containing the core locus tags and a true/false table.
    """
    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    roary_out_dir = os.path.join(conservation_dir, 'roary_output')
    gff_dir = os.path.join(roary_out_dir,'gff')
    results_dir = os.path.join(roary_out_dir, 'results')
    roary_results_table = os.path.join(conservation_dir, 'core_roary.tsv')

    if os.path.exists(results_dir):
        fixed_input_dir = os.path.join(results_dir, 'fixed_input_files')
        genes_csv_file = os.path.join(results_dir, 'gene_presence_absence.csv')

        if os.path.exists(genes_csv_file):

            if not files.file_check(roary_results_table):
                dtypes = {'No. isolates': 'int', f'{organism_name}': 'str'}
                df = pd.read_csv(genes_csv_file, usecols= ['No. isolates', f'{organism_name}'], dtype=dtypes)
                max_isolates = df['No. isolates'].max()
                print(f'Total genomes analyzed by Roary: {max_isolates}')
                max_isolates_rows = df[df['No. isolates'] >= int(max_isolates)*core_threshold]
                print(f'Roary total core genes (> {core_threshold*100}% strains): {len(max_isolates_rows)}')
                gbk_ids = max_isolates_rows[f'{organism_name}'].dropna().tolist()
                print(f'Roary {organism_name} core genes: {len(gbk_ids)}')

                gff_file = os.path.join(gff_dir, f'{organism_name}.gff')
                gff_file_fixed = os.path.join(fixed_input_dir, f'{organism_name}.gff')
                if os.path.exists(gff_file_fixed):
                    print(f'Reading {gff_file_fixed}')
                    core_locus_tag = id_to_locustag_gff(gff_file_fixed, gbk_ids, fix=True)
                elif os.path.exists(gff_file):
                    print(f'Reading {gff_file}')
                    core_locus_tag = id_to_locustag_gff(gff_file, gbk_ids)
                else:
                    logging.error(f'{organism_name}.gff not found.')

                roary_table = metadata.metadata_table_bool(output_path, organism_name, core_locus_tag, 'core_roary', conservation_dir)
            else:
                print(f'Roary output file already exists: {roary_results_table}.')
                roary_table = pd.read_csv(roary_results_table, sep='\t', index_col=0, header=0)
        else:
            logging.error('No roary "gene_presence_absence.csv" file found.')
    else:
        logging.error(f'No roary output found in {roary_out_dir}.')


    return roary_table

def corecruncher_output(output_path, organism_name):
    
    """
    Process the output from CoreCruncher for the given organism.

    This function processes the output file 'families_core.txt' generated by CoreCruncher for the specified organism.
    It reads the file to extract the core locus tags and generates a metadata table with these IDs.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    
    :return: A list containing the core locus tags and a true/false table.
    """
        
    conservation_dir = os.path.join(output_path, organism_name, 'conservation')
    cc_output_file = os.path.join(conservation_dir, 'corecruncher_output', 'families_core.txt')
    ref_genome = f'{organism_name}.faa'
    cc_results_table = os.path.join(conservation_dir, 'core_corecruncher.tsv')

    core_locus_tag = []
    core_total = 0

    if not files.file_check(cc_results_table):
        if os.path.exists(cc_output_file):
            with open(cc_output_file, 'r') as tsvfile:
                reader = csv.reader(tsvfile, delimiter='\t')
                for row in reader:
                    core_total += 1
                    for value in row:
                        if isinstance(value, str) and value.startswith(ref_genome):
                            core_locus_tag.append(value.split('&')[1])
        else:
            logging.error(f"Corecruncher output file '{cc_output_file}' not found.")

        print(f'CoreCruncher total core genes (> 90% strains): {core_total}')
        print(f'CoreCruncher {organism_name} core genes: {len(core_locus_tag)}')

        corecruncher_table = metadata.metadata_table_bool(output_path, organism_name, core_locus_tag, 'core_corecruncher',conservation_dir)
    else:
        print(f'CoreCruncher output file already exists: {cc_results_table}.')
        corecruncher_table = pd.read_csv(cc_results_table, sep='\t', index_col=0, header=0)

    return corecruncher_table

def localization_prediction(output_path, organism_name, organism_type, container_engine='docker'):

    """
    Predicts the subcellular localization of proteins using PSORTb.
    
    This function predicts the subcellular localization of proteins for the given organism using PSORTb.
    It first checks if a localization prediction has already been performed and saved to disk.
    If not, it runs PSORTb to predict the localization and saves the results to disk.
    This function uses the `run_psort` function from the `programs` module.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param organism_type: Type of organism, can be 'a' (archaea), 'n' (gram-negative bacteria), or 'p' (gram-positive bacteria).
    :param container_engine: Container engine to use ('docker' or 'singularity').

    :return: A dictionary with the localization predictions for each protein.
    
    """
    
    valid_type = ['a','n','p']
    if organism_type not in valid_type:
        raise ValueError("output_dir must be one of %r." % valid_type)
    
    faa_path = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.faa')
    localization_dir = os.path.join(output_path, organism_name, 'localization')

    file_pattern = os.path.join(localization_dir, "*_psortb_*.txt")
    all_files = glob.glob(file_pattern)

    if not all_files:
        programs.run_psort(faa_path, organism_type, localization_dir, output_format='terse', container_engine=container_engine)
        # After running, find the newly created file
        all_files = glob.glob(file_pattern)
        if not all_files:
            raise FileNotFoundError(f"PSORTb ran but no output file found in {localization_dir}")
    
    if len(all_files) > 1:
        raise FileNotFoundError(f"Multiple psort result files found in {localization_dir}. Leave only one.")
    
    # Process PSORTb results
    print(f"Processing PSORTb results from {all_files[0]}")
    
    psort_results = os.path.join(localization_dir, 'psortb_localization.tsv')

    if not files.file_check(psort_results):
        # Parse the PSORTb output file
        file_path = all_files[0]
        df = pd.read_csv(file_path, sep=r'\s+', usecols=[0, 1])

        result_dict = df.set_index('SeqID')['Localization'].to_dict()

        psort_df = metadata.metadata_table_with_values(output_path, organism_name, result_dict,'psortb_localization',localization_dir, 'Unknown')

        return psort_df
    else:
        # Load previously processed results
        print(f"Loading previously processed PSORTb results from {psort_results}")
        psort_df = pd.read_csv(psort_results, sep='\t', index_col=0, header=0)

        return psort_df
        
    

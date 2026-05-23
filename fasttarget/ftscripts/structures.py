import os
import sys
import urllib.request
from tqdm import tqdm
import pandas as pd
import re
import csv
import tempfile
from Bio import SeqIO
import multiprocessing
from pathlib import Path
from Bio.PDB import PDBParser, PDBIO, Select
from ftscripts import programs, files, metadata
import databases
import glob
import shutil
import logging
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
import requests
import xml.etree.ElementTree as ET
import time
from functools import wraps  
from urllib3.exceptions import SSLError
from requests.exceptions import (
    SSLError as RequestsSSLError, 
    ConnectionError, 
    Timeout
)
from datetime import datetime


## ------------------- UNIPROT PROTEOME FUNCTIONS ------------------- ##

def parse_pdb_refs(pdb_string):
    """
    Parse PDB references from metadata string
    E.g., "1ABC;2DEF;3GHI" -> ["1ABC", "2DEF", "3GHI"]
    """
    if pd.isna(pdb_string) or pdb_string == "":
        return []
    else:
        return [pdb.strip() for pdb in str(pdb_string).split(';') if pdb.strip()]

def count_fasta_sequences(fasta_file):
    """
    Count the number of sequences in a FASTA file.
    
    :param fasta_file: Path to FASTA file.
    :return: Number of sequences in the file, or 0 if file doesn't exist or is invalid.
    """
    if not os.path.exists(fasta_file):
        return 0
    
    try:
        count = 0
        with open(fasta_file, 'r') as f:
            for record in SeqIO.parse(f, 'fasta'):
                count += 1
        return count
    except Exception as e:
        logging.warning(f"Could not count sequences in {fasta_file}: {e}")
        return 0

@databases.retry_with_backoff(max_retries=10, initial_delay=2, backoff_factor=2, max_delay=80)
def fetch_uniprot_xml(uniprot_id):
    """
    Fetch UniProt XML data with automatic retry on network/SSL errors.
    
    Uses the retry_with_backoff decorator from databases module for robust
    error handling with exponential backoff.
    
    :param uniprot_id: UniProt accession ID.
    :return: XML content as bytes.
    :raises: requests.exceptions.RequestException if all retries fail.
    """
    uniprot_url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}?format=xml"
    
    # Add User-Agent header to identify the tool
    headers = {
        'User-Agent': 'FastTarget/1.0',
        'Accept': 'application/xml'
    }
    
    response = requests.get(uniprot_url, headers=headers, timeout=30)
    response.raise_for_status()  # Raise exception for bad status codes
    
    return response.content

@databases.retry_with_backoff(max_retries=10, initial_delay=2, backoff_factor=2, max_delay=80)
def fetch_uniprot_batch_xml(uniprot_ids):
    """
    Fetch UniProt XML data for MULTIPLE UniProt IDs in a single batch request.
    
    Uses UniProt's batch endpoint: /uniprotkb/accessions?accessions=ID1,ID2,ID3
    Returns a single XML document containing multiple <entry> elements.
    
    :param uniprot_ids: List of UniProt accession IDs (max 500 recommended).
    :return: XML content as bytes containing all entries.
    :raises: requests.exceptions.RequestException if all retries fail.
    """
    if not uniprot_ids:
        return b'<?xml version="1.0" encoding="UTF-8"?><uniprot xmlns="http://uniprot.org/uniprot"></uniprot>'
    
    # Join IDs with commas (UniProt batch endpoint format)
    ids_string = ",".join(uniprot_ids)
    uniprot_url = f"https://rest.uniprot.org/uniprotkb/accessions?accessions={ids_string}&format=xml"
    
    headers = {
        'User-Agent': 'FastTarget/1.0',
        'Accept': 'application/xml'
    }
    
    logging.info(f"Fetching batch of {len(uniprot_ids)} UniProt entries...")
    response = requests.get(uniprot_url, headers=headers, timeout=60)
    response.raise_for_status()
    
    return response.content

def parse_uniprot_entry_xml(entry_element):
    """
    Parse a single UniProt <entry> XML element into annotation dictionary.
    
    Extracted from uniprot_protein_annotations() to allow reuse for both
    single and batch queries.
    
    :param entry_element: ElementTree Element representing a single <entry>.
    :return: Dictionary with annotations {uniprot_id: {annotation_data}}, or None if parsing fails.
    """
    try:
        namespaces = {'up': 'http://uniprot.org/uniprot'}
        
        # Extract accession number
        accession_elem = entry_element.find('up:accession', namespaces)
        if accession_elem is None:
            logging.warning("No accession found in entry")
            return None
        
        accession = accession_elem.text
        version = entry_element.attrib.get('version')
        dataset = entry_element.attrib.get('dataset')
        
        result = {accession: {'Version': version, 'Dataset': dataset}}
        
        # Extract protein names
        recommended_name = entry_element.findall('up:protein/up:recommendedName/up:fullName', namespaces)
        submitted_name = entry_element.findall('up:protein/up:submittedName/up:fullName', namespaces)
        
        if recommended_name:
            result[accession]['Protein_name'] = recommended_name[0].text
        elif submitted_name:
            result[accession]['Protein_name'] = submitted_name[0].text
        else:
            result[accession]['Protein_name'] = None
        
        # Extract gene names (locus tags)
        ordered_locus = entry_element.findall('up:gene/up:name[@type="ordered locus"]', namespaces)
        if ordered_locus:
            result[accession]['Locus_tag'] = [gene_name.text for gene_name in ordered_locus]
        else:
            result[accession]['Locus_tag'] = None
        
        # Extract EC number
        catalytic_activity_comment = entry_element.find('.//up:comment[@type="catalytic activity"]', namespaces)
        if catalytic_activity_comment is not None:
            reaction = catalytic_activity_comment.find('up:reaction', namespaces)
            if reaction is not None:
                ec_reference = reaction.find('up:dbReference[@type="EC"]', namespaces)
                result[accession]['EC_number'] = ec_reference.get('id') if ec_reference is not None else None
            else:
                result[accession]['EC_number'] = None
        else:
            result[accession]['EC_number'] = None
        
        # Extract RefSeq IDs
        refseq = entry_element.findall('.//up:dbReference[@type="RefSeq"]', namespaces)
        result[accession]['Refseq_ProtID'] = None
        if refseq:
            refseq_ids = []
            for refseq_id in refseq:
                id_refseq = refseq_id.get('id')
                if id_refseq:
                    refseq_ids.append(id_refseq)
            refseq_ids = list(set(refseq_ids))  # Remove duplicates   
            if refseq_ids:
                result[accession]['Refseq_ProtID'] = refseq_ids if len(refseq_ids) > 1 else refseq_ids[0]
            else:
                result[accession]['Refseq_ProtID'] = None 

        # Extract AlphaFold IDs
        alphafold = entry_element.findall('.//up:dbReference[@type="AlphaFoldDB"]', namespaces)
        result[accession]['AlphaFoldDB'] = alphafold[0].get('id') if alphafold else None
        
        # Extract PDB references
        pdb_references = entry_element.findall('.//up:dbReference[@type="PDB"]', namespaces)
        if pdb_references:
            pdb_list = []
            for pdb_ref in pdb_references:
                pdb_id = pdb_ref.get('id')
                properties = pdb_ref.findall('up:property', namespaces)
                pdb_info = {"ID": pdb_id}
                for prop in properties:
                    pdb_info[prop.get('type')] = prop.get('value')
                pdb_list.append(pdb_info)
            result[accession]['PDB_id'] = pdb_list
        else:
            result[accession]['PDB_id'] = None
        
        # Extract sequence
        sequence_element = entry_element.find('up:sequence', namespaces)
        result[accession]['Sequence'] = sequence_element.text if sequence_element is not None else None
        
        return result
        
    except Exception as e:
        logging.exception(f"Failed to parse UniProt entry: {e}")
        return None

def uniprot_protein_annotations(uniprot_id):
    """
    Return a dictionary with annotations for a UniProt ID: Dataset, Protein name, Refseq ID, Sequence, 
    Version, EC, Locus_tag and PDB/Alphafold IDs. 

    :param uniprot_id: UniProt ID.
    :return: Dictionary with annotations for the UniProt ID, or None if failed.
    """
    
    try:
        # Use retry-enabled fetch function
        uniprot_xml = fetch_uniprot_xml(uniprot_id)
        
        root = ET.fromstring(uniprot_xml)
        namespaces = {'up': 'http://uniprot.org/uniprot'}

        # Extract accession number
        accession = root.find('up:entry/up:accession', namespaces).text
        version = root.find('up:entry', namespaces).attrib['version']
        dataset = root.find('up:entry', namespaces).attrib['dataset']

        if accession != uniprot_id:
            logging.warning(f"Accession mismatch: requested {uniprot_id}, got {accession}")
            return None

        result = {accession: {'Version': version, 'Dataset': dataset}}

        # Extract protein names
        recommended_name = root.findall('up:entry/up:protein/up:recommendedName/up:fullName', namespaces)
        submitted_name = root.findall('up:entry/up:protein/up:submittedName/up:fullName', namespaces)

        if recommended_name:
            result[accession]['Protein_name'] = [protein_name.text for protein_name in recommended_name][0]
        elif submitted_name:
            result[accession]['Protein_name'] = [protein_name.text for protein_name in submitted_name][0]
        else:
            result[accession]['Protein_name'] = None

        # Extract gene names
        ordered_locus = root.findall('up:entry/up:gene/up:name[@type="ordered locus"]', namespaces)
        if ordered_locus:
            result[accession]['Locus_tag'] = [gene_name.text for gene_name in ordered_locus]
        else:
            result[accession]['Locus_tag'] = None

        # Find the catalytic activity comment
        catalytic_activity_comment = root.find('.//up:comment[@type="catalytic activity"]', namespaces)
        if catalytic_activity_comment is not None:
            reaction = catalytic_activity_comment.find('up:reaction', namespaces)
            if reaction is not None:
                ec_reference = reaction.find('up:dbReference[@type="EC"]', namespaces)
                if ec_reference is not None:
                    result[accession]['EC_number'] = ec_reference.get('id')
                else:
                    result[accession]['EC_number'] = None
            else:
                result[accession]['EC_number'] = None
        else:
            result[accession]['EC_number'] = None

        # Find Refseq references
        refseq = root.findall('.//up:dbReference[@type="RefSeq"]', namespaces)
        if refseq:
            refseq_ids = []
            for refseq_id in refseq:
                id_refseq = refseq_id.get('id')
                if id_refseq:
                    refseq_ids.append(id_refseq)
            refseq_ids = list(set(refseq_ids))  # Remove duplicates
            if refseq_ids:
                result[accession]['Refseq_ProtID'] = refseq_ids if len(refseq_ids) > 1 else refseq_ids[0]
            else:
                result[accession]['Refseq_ProtID'] = None
        else:
            result[accession]['Refseq_ProtID'] = None

        # Find Alphafold ids
        alphafold = root.findall('.//up:dbReference[@type="AlphaFoldDB"]', namespaces)
        if alphafold:
            alphafold_ids = []
            for alphafold_id in alphafold:
                id_af = alphafold_id.get('id')
                alphafold_ids.append(id_af)
            alphafold_ids = list(set(alphafold_ids))  # Remove duplicates
            if alphafold_ids:
                result[accession]['AlphaFoldDB'] = alphafold_ids if len(alphafold_ids) > 1 else alphafold_ids[0]
            else:
                result[accession]['AlphaFoldDB'] = None
        else:
            result[accession]['AlphaFoldDB'] = None

        # Find PDB references
        pdb_references = root.findall('.//up:dbReference[@type="PDB"]', namespaces)
        if pdb_references:
            pdb_list = []
            for pdb_ref in pdb_references:
                pdb_id = pdb_ref.get('id')
                properties = pdb_ref.findall('up:property', namespaces)
                pdb_info = {"ID": pdb_id}
                for prop in properties:
                    prop_type = prop.get('type')
                    prop_value = prop.get('value')
                    pdb_info[prop_type] = prop_value
                pdb_list.append(pdb_info)
            result[accession]['PDB_id'] = pdb_list
        else:
            result[accession]['PDB_id'] = None

        # Extract sequence
        sequence_element = root.find('up:entry/up:sequence', namespaces)
        if sequence_element is not None:
            sequence = sequence_element.text
            result[accession]['Sequence'] = sequence
        else:
            result[accession]['Sequence'] = None
            
        return result
        
    except Exception as e:
        logging.exception(f"Failed to fetch annotations for {uniprot_id} after all retries: {e}")
        return None

def uniprot_protein_annotations_batch(uniprot_ids, batch_size=500):
    """
    Return a dictionary with annotations for MULTIPLE UniProt IDs using batch queries.
    
    Fetches data from UniProt REST API in batches (default 500 IDs per request).
    Returns combined annotations for all requested IDs.
    
    :param uniprot_ids: List of UniProt accession IDs.
    :param batch_size: Number of IDs to fetch per request (default 500, max ~1000).
    :return: Dictionary with annotations {uniprot_id: {annotation_data}} or empty dict if failed.
    """
    if not uniprot_ids:
        return {}
    
    all_annotations = {}
    total_batches = (len(uniprot_ids) + batch_size - 1) // batch_size
    
    logging.info(f"Fetching annotations for {len(uniprot_ids)} UniProt IDs in {total_batches} batch(es)...")
    
    for i in range(0, len(uniprot_ids), batch_size):
        batch = uniprot_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        logging.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} entries)...")
        
        try:
            # Fetch batch XML
            batch_xml = fetch_uniprot_batch_xml(batch)
            
            # Parse batch XML
            root = ET.fromstring(batch_xml)
            namespaces = {'up': 'http://uniprot.org/uniprot'}
            
            # Find all entry elements in batch response
            entries = root.findall('up:entry', namespaces)
            logging.info(f"  Found {len(entries)} entries in batch response")
            
            # Parse each entry
            for entry in entries:
                entry_result = parse_uniprot_entry_xml(entry)
                if entry_result:
                    all_annotations.update(entry_result)
            
            # Log batch progress
            logging.info(f"  ✓ Batch {batch_num} complete: {len(all_annotations)}/{len(uniprot_ids)} total annotations retrieved")
            
            # Small delay between batches to be respectful to API
            if i + batch_size < len(uniprot_ids):
                time.sleep(2)
                
        except Exception as e:
            logging.exception(f"Failed to process batch {batch_num}: {e}")
            continue
    
    # Summary
    success_rate = (len(all_annotations) / len(uniprot_ids)) * 100 if uniprot_ids else 0
    logging.info(f"Batch fetch complete: {len(all_annotations)}/{len(uniprot_ids)} annotations retrieved ({success_rate:.1f}%)")
    
    # Log missing IDs
    missing_ids = set(uniprot_ids) - set(all_annotations.keys())
    if missing_ids:
        logging.warning(f"Missing annotations for {len(missing_ids)} IDs: {list(missing_ids)[:10]}{'...' if len(missing_ids) > 10 else ''}")
    
    return all_annotations

def download_species_uniprot_data(output_path, organism_name, specie_taxid):
    """
    Download all UniProt data for a taxonomic ID (species-level)
    Including sequences, strain information and structure availability
    
    :param output_path: Directory to save the data
    :param organism_name: Name of organism.
    :param specie_taxid: Species Taxonomy ID (e.g. 287 for P. aeruginosa)

    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    output_path = os.path.join(structure_dir, 'uniprot_files')

    os.makedirs(output_path, exist_ok=True)
       
    # Download data from Uniprot, including strain and structure information
    uniptot_url = f"https://rest.uniprot.org/uniprotkb/stream?format=tsv&query=taxonomy_id:{specie_taxid}&fields=accession,id,reviewed,annotation_score,protein_name,organism_name,organism_id,length,xref_pdb,xref_alphafolddb,sequence"
    uniptot_file = os.path.join(output_path, f"uniprot_specie_taxid_{specie_taxid}_data.tsv")
    
    if not files.file_check(uniptot_file):
        print(f"Downloading metadata for Tax ID {specie_taxid}...")
        databases.download_with_progress(uniptot_url, uniptot_file)
    else:
        print(f"UniProt data for Tax ID {specie_taxid} already exists at {uniptot_file}. Skipping download.")

def parse_uniprot_species_data(uniptot_file, specie_taxid, strain_taxid):
    """
    Parse downloaded UniProt data into FASTA files for:
    1) Strain-specific proteins
    2) Proteins with PDB structures for the species
    3) Rest of species proteins (no PDB, not strain)

    :param uniptot_file: Path to the downloaded UniProt TSV file with species data
    :param specie_taxid: Species Taxonomy ID (e.g. 287 for P. aeruginosa)
    :param strain_taxid: Strain Taxonomy ID (e.g. 208964 for PAO1)
    """

    if files.file_check(uniptot_file) is False:
        print(f"Error: File {uniptot_file} does not exist or is empty.")
        raise FileNotFoundError(f'{uniptot_file} not found.')
    else:
        # Parse UniProt species data
        # Keep Entry and PDB columns as string to prevent scientific notation
        uniprot_df = pd.read_csv(uniptot_file, sep='\t', dtype={'Entry': str, 'PDB': str})

        # 1) Obtain strain specific data
        strain_df = uniprot_df[uniprot_df['Organism (ID)'] == strain_taxid]

        fasta_file = os.path.join(
            os.path.dirname(uniptot_file),
            f"uniprot_strain_taxid_{strain_taxid}.faa")
        with open(fasta_file, 'w') as fasta_out:
            for _, row in strain_df.iterrows():
                fasta_out.write(f">{row['Entry']}\n{row['Sequence']}\n")
        print(f"UniProt strain-specific FASTA file created: {fasta_file}")
        # 2) Obtain proteins with PDB structure data
        structure_df = uniprot_df[(uniprot_df['PDB'].notna())] 
        fasta_file_struct = os.path.join(
            os.path.dirname(uniptot_file),
            f"uniprot_PDB_structures_specie_taxid_{specie_taxid}.faa")
        with open(fasta_file_struct, 'w') as fasta_out:
            for _, row in structure_df.iterrows():
                fasta_out.write(f">{row['Entry']}\n{row['Sequence']}\n")
        print(f"UniProt PDB structure FASTA file created: {fasta_file_struct}")
        # 3) Obtain the rest of UniProt proteins for the species
        rest_mask = (~uniprot_df['Entry'].isin(strain_df['Entry']) &
                        ~uniprot_df['Entry'].isin(structure_df['Entry']))
        rest_df = uniprot_df[rest_mask]
        # Order rest_df by reviewed status
        rest_df = rest_df.sort_values(
            by=['Reviewed', 'Annotation'],
            ascending=[True, False])

        fasta_file_species_rest = os.path.join(
            os.path.dirname(uniptot_file),
            f"uniprot_species_taxid_{specie_taxid}_rest.faa")
        with open(fasta_file_species_rest, 'w') as fasta_out:
            for _, row in rest_df.iterrows():
                fasta_out.write(f">{row['Entry']}\n{row['Sequence']}\n")
        print(f"Uniprot species REST FASTA file created: {fasta_file_species_rest}")

def cluster_uniprot_specie(output_path, organism_name, specie_taxid):
    """
    Cluster uniprot proteins at 100% identity and a minimum alignment coverage of 90% using CD-HIT.
    This function uses the `run_cd_hit` function from the `programs` module.
    Clustered sequences are saved in a new .faa file.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param specie_taxid: Species Taxonomy ID.

    """
    uniprot_dir = os.path.join(output_path, organism_name, 'structures', 'uniprot_files')
    uniprot_species_rest_faa = os.path.join(uniprot_dir, f"uniprot_species_taxid_{specie_taxid}_rest.faa")
    output_cdhit_file = uniprot_species_rest_faa.replace('.faa', '_cdhit100.faa')

    if not files.file_check(output_cdhit_file):
        try:
            programs.run_cd_hit(
                input_fasta= uniprot_species_rest_faa,
                output_fasta= output_cdhit_file,
                identity= 1.0,
                aln_coverage_short= 0.9,
                aln_coverage_long= 0.9,
                use_global_seq_identity= True,
                accurate_mode= True,
                cpus= multiprocessing.cpu_count()
            )
        except Exception as e:
            logging.exception(f"Failed to run CD-HIT on file {uniprot_species_rest_faa}: {e}")
    else:
        print(f'Clustered uniprot species-level rest proteome already exists: {output_cdhit_file}')

def create_uniprot_blast_db (output_path, organism_name, specie_taxid, strain_taxid):
    
    """
    Runs NCBI makeblastdb against uniprot proteome. Do this for:
    1) Strain-specific proteome
    2) PDB structure proteome (specie-level)
    3) Rest of proteome (specie-level, clustered with CD-HIT)

    This function uses the `run_makeblastdb` function from the `programs` module.
    Database is saved in the structures directory.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param proteome_id: Uniprot proteome ID.
    """

    uniprot_dir = os.path.join(output_path, organism_name, 'structures', 'uniprot_files')

    # For strain-specific database
    uniprot_strain_faa = os.path.join(uniprot_dir, f"uniprot_strain_taxid_{strain_taxid}.faa")
    uniprot_strain_index_path = os.path.join(uniprot_dir, f'uniprot_strain_taxid_{strain_taxid}')
    
    blast_output_strain_path= os.path.join(uniprot_dir, f'uniprot_strain_taxid_{strain_taxid}_blast.tsv')

    # Check if strain-specific faa file exists and has sequences
    strain_seq_count = count_fasta_sequences(uniprot_strain_faa)
    strain_faa_exists = strain_seq_count > 0
    
    #Index
    if strain_faa_exists and not files.file_check(blast_output_strain_path):
        print(f'Indexing uniprot strain-specific proteome for taxid {strain_taxid} ({strain_seq_count} sequences)')
    
        try:
            programs.run_makeblastdb(
            input= uniprot_strain_faa,
            output= uniprot_strain_index_path,
            title= f'uniprot_strain_taxid_{strain_taxid}',
            dbtype= 'prot'
            )
            print(f'Index built for strain uniprot proteome: uniprot_strain_taxid_{strain_taxid}')
        except Exception as e:
            logging.exception(f"Failed to run makeblastdb to file {uniprot_strain_faa}: {e}")
    elif strain_faa_exists:
        print(f'Index already exists for strain uniprot proteome: uniprot_strain_taxid_{strain_taxid}')
    else:
        print(f'WARNING: No strain-specific proteins found for taxid {strain_taxid} (file has {strain_seq_count} sequences). Skipping strain database creation and will use species-level data only.')

    # For PDB structure database
    uniprot_pdb_faa = os.path.join(uniprot_dir, f"uniprot_PDB_structures_specie_taxid_{specie_taxid}.faa")
    uniprot_pdb_index_path = os.path.join(uniprot_dir, f'uniprot_PDB_structures_specie_taxid_{specie_taxid}')
    
    blast_output_pdb_path= os.path.join(uniprot_dir, f'uniprot_PDB_structures_specie_taxid_{specie_taxid}_blast.tsv')

    #Index
    if not files.file_check(blast_output_pdb_path):
        print(f'Indexing uniprot PDB structure proteome for taxid {specie_taxid}')
    
        try:
            programs.run_makeblastdb(
            input= uniprot_pdb_faa,
            output= uniprot_pdb_index_path,
            title= f'uniprot_PDB_structures_specie_taxid_{specie_taxid}',
            dbtype= 'prot'
            )
            print(f'Index built for PDB uniprot proteome: uniprot_PDB_structures_specie_taxid_{specie_taxid}')
        except Exception as e:
            logging.exception(f"Failed to run makeblastdb to file {uniprot_pdb_faa}: {e}")
    else:
        print(f'Index already exists for PDB uniprot proteome: uniprot_PDB_structures_specie_taxid_{specie_taxid}')
    
    # For rest of uniprot protein (specie-level)
    uniprot_species_rest_faa = os.path.join(uniprot_dir, f"uniprot_species_taxid_{specie_taxid}_rest_cdhit100.faa")
    uniprot_species_rest_index_path = os.path.join(uniprot_dir, f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100')

    blast_output_species_rest_path= os.path.join(uniprot_dir, f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100_blast.tsv')

    #Index
    if not files.file_check(blast_output_species_rest_path):
        print(f'Indexing uniprot species-level rest proteome for taxid {specie_taxid}')

        try:
            programs.run_makeblastdb(
            input= uniprot_species_rest_faa,
            output= uniprot_species_rest_index_path,
            title= f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100',
            dbtype= 'prot'
            )
            print(f'Index finished for species-level rest uniprot proteome: uniprot_species_taxid_{specie_taxid}_rest_cdhit100')
        except Exception as e:
            logging.exception(f"Failed to run makeblastdb to file {uniprot_species_rest_faa}: {e}")
    else:
        print(f'Index already exists for species-level rest uniprot proteome: uniprot_species_taxid_{specie_taxid}_rest_cdhit100')   

def uniprot_proteome_blast (output_path, organism_name, specie_taxid, strain_taxid, cpus=multiprocessing.cpu_count()):
    """
    Runs NCBI Blastp against uniprot proteome databases. Do this for:
    1) Strain-specific proteome
    2) PDB structure proteome (specie-level)
    3) Rest of proteome (specie-level, clustered with CD-HIT)
    This function uses the `run_blastp` function from the `programs` module. 
    Results are saved in a .tsv file in the structures/uniprot_files directory, with separate files for each database.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param specie_taxid: Species Taxonomy ID.
    :param strain_taxid: Strain Taxonomy ID.
    :param cpus: Number of threads (CPUs) to use in blast search.
    """

    uniprot_dir = os.path.join(output_path, organism_name, 'structures', 'uniprot_files')

    # Query: proteins from the organism genome
    organism_prot_seq_path = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.faa')

    # For strain-specific database
    uniprot_strain_faa = os.path.join(uniprot_dir, f"uniprot_strain_taxid_{strain_taxid}.faa")
    uniprot_strain_index_path = os.path.join(uniprot_dir, f'uniprot_strain_taxid_{strain_taxid}')
    blast_output_strain_path= os.path.join(uniprot_dir, f'uniprot_strain_taxid_{strain_taxid}_blast.tsv')
    
    # Check if strain-specific faa file exists and has sequences
    strain_seq_count = count_fasta_sequences(uniprot_strain_faa)
    strain_faa_exists = strain_seq_count > 0
    
    if strain_faa_exists and not files.file_check(blast_output_strain_path):
        print(f'Running blastp for {organism_name} and uniprot strain-specific proteome taxid {strain_taxid} ({strain_seq_count} sequences)')

        try:
            programs.run_blastp(
                blastdb= uniprot_strain_index_path,
                query= organism_prot_seq_path,
                output=blast_output_strain_path,
                evalue= '1e-5',
                outfmt= '6 std qcovhsp qcovs qlen slen',
                max_target_seqs = '5',
                cpus=cpus
            )
            print(f'Blastp finished for uniprot strain-specific proteome taxid {strain_taxid}')
            print(f'Blastp results saved in {blast_output_strain_path}.')

        except Exception as e:
            logging.exception(f"Failed to run blastp to file {uniprot_strain_index_path}: {e}")
    elif strain_faa_exists:
        print(f'Blastp results in {blast_output_strain_path}.')
    else:
        print(f'WARNING: No strain-specific proteins found for taxid {strain_taxid} (file has {strain_seq_count} sequences). Skipping strain BLAST and will use species-level data only.')
   
    # For PDB structure database
    uniprot_pdb_index_path = os.path.join(uniprot_dir, f'uniprot_PDB_structures_specie_taxid_{specie_taxid}')
    blast_output_pdb_path= os.path.join(uniprot_dir, f'uniprot_PDB_structures_specie_taxid_{specie_taxid}_blast.tsv')

    if not files.file_check(blast_output_pdb_path):
        print(f'Runing blastp for {organism_name} and uniprot PDB structure proteome for taxid {specie_taxid}')

        try:
            programs.run_blastp(
                blastdb= uniprot_pdb_index_path,
                query= organism_prot_seq_path,
                output=blast_output_pdb_path,
                evalue= '1e-5',
                outfmt= '6 std qcovhsp qcovs qlen slen',
                max_target_seqs = '5',
                cpus=cpus
            )
            print(f'Blastp finished for uniprot PDB structure proteome for taxid {specie_taxid}')
            print(f'Blastp results saved in {blast_output_pdb_path}.')

        except Exception as e:
            logging.exception(f"Failed to run blastp to file {uniprot_pdb_index_path}: {e}")
    else:
        print(f'Blastp results in {blast_output_pdb_path}.')

    # For rest of uniprot protein (specie-level)
    uniprot_species_rest_index_path = os.path.join(uniprot_dir, f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100')
    blast_output_species_rest_path= os.path.join(uniprot_dir, f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100_blast.tsv')


    if not files.file_check(blast_output_species_rest_path):
        print(f'Runing blastp for {organism_name} and uniprot Specie structure proteome for taxid {specie_taxid}')

        try:
            programs.run_blastp(
                blastdb= uniprot_species_rest_index_path,
                query= organism_prot_seq_path,
                output=blast_output_species_rest_path,
                evalue= '1e-5',
                outfmt= '6 std qcovhsp qcovs qlen slen',
                max_target_seqs = '5',
                cpus=cpus
            )
            print(f'Blastp finished for uniprot Specie structure proteome for taxid {specie_taxid}')
            print(f'Blastp results saved in {blast_output_species_rest_path}.')

        except Exception as e:
            logging.exception(f"Failed to run blastp to file {uniprot_species_rest_index_path}: {e}")
    else:
        print(f'Blastp results in {blast_output_species_rest_path}.')

def parse_best_result_blast (file, identity_cutoff=95, coverage_cutoff=90, subject_cov_cutoff=90, all_hits=False):
    """
    Parse blast output and return best hit per query based on identity and coverage.

    :param file: Path to blast output file.
    :param identity_cutoff: Minimum percentage identity to consider a hit. Default is 95.
    :param coverage_cutoff: Minimum query coverage to consider a hit. Default is 90.
    :param subject_cov_cutoff: Minimum subject coverage to consider a hit. Default is 90.
    :param all_hits: If True, return all hits that meet the criteria. If False, return only the best hit. Default is False.
    :return: Dictionary with query id as key and best subject id as value.
    """

    print(f'Reading blastp results for {file}.')

    # Check if file exists and has content
    if not os.path.exists(file) or os.path.getsize(file) == 0:
        print(f'WARNING: BLAST output file {file} is empty or does not exist. Returning empty results.')
        return {}

    try:
        blast_output_df = files.read_blast_output(file, len=True)
    except Exception as e:
        print(f'WARNING: Could not parse BLAST output file {file}: {e}. Returning empty results.')
        return {}
    
    # Check if dataframe is empty
    if blast_output_df.empty:
        print(f'WARNING: BLAST output file {file} contains no results. Returning empty results.')
        return {}

    blast_output_df['scov'] = (blast_output_df['length'] / blast_output_df['slen']) * 100
    # Apply filters
    blast_output_filtered_df = blast_output_df[(blast_output_df['pident'] >= identity_cutoff) & 
                                                (blast_output_df['qcovs'] >= coverage_cutoff) & 
                                                (blast_output_df['scov'] >= subject_cov_cutoff)]

    best_hits = {}

    for qseqid, group in blast_output_filtered_df.groupby('qseqid'):

        # Find the maximum identity value in the group
        max_identity = group['pident'].max()
        # Filter rows that have the maximum identity
        best_identity = group[group['pident'] == max_identity]

        # Find the maximum coverage value in the group
        max_coverage = best_identity['qcovs'].max()
        # Filter rows that have the maximum coverage
        best_results = best_identity[best_identity['qcovs'] == max_coverage]

        if all_hits:
            best_hits[qseqid] = best_results['sseqid'].tolist()
        else:
            best_hits[qseqid] = best_results['sseqid'].iloc[0]

    return best_hits

def uniprot_proteome_mapping (output_path, organism_name, specie_taxid, strain_taxid):

    """
    Map locus_tags to uniprot ids using blastp results for specie specific proteome.
    Follows this priorrity to asign uniprot ids:
    1) Look for proteins that have an structures in PDB (specie-level)
    2) Map proteins to strain-specific uniprot proteome
    3) Map proteins to rest of specie-level uniprot proteome (cross-strain search)

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param strain_taxid: Strain Taxonomy ID.
    :return: Dictionary with locus_tag as key and list of uniprot ids as values.

    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    uniprot_dir = os.path.join(structure_dir, 'uniprot_files')
    
    # Blastp search result files
    # PDB
    blast_output_pdb_path= os.path.join(uniprot_dir, f'uniprot_PDB_structures_specie_taxid_{specie_taxid}_blast.tsv')
    # Strain specific 
    blast_output_strain_path= os.path.join(uniprot_dir, f'uniprot_strain_taxid_{strain_taxid}_blast.tsv')
    # Rest of Uniprot 
    blast_output_species_rest_path= os.path.join(uniprot_dir, f'uniprot_species_taxid_{specie_taxid}_rest_cdhit100_blast.tsv')

    # File with mapping IDs 
    proteome_ids_file = os.path.join(uniprot_dir, f'uniprot_{organism_name}_id_mapping.json')

    if not files.file_check(proteome_ids_file):
           
        # 1) Map with IDs with PDB structures
        if files.file_check(blast_output_pdb_path):
            parse_pdb = parse_best_result_blast (blast_output_pdb_path, 
                                    identity_cutoff=95, 
                                    coverage_cutoff=90,
                                    subject_cov_cutoff=90,
                                    all_hits=True)
        else:
            parse_pdb = {}
            logging.warning(f'No PDB BLAST results found. Continuing with strain/species-level data only.')
            print(f'WARNING: No PDB BLAST results found. Continuing with strain/species-level data only.')
        
        # 2) Map with IDs within the strain
        if files.file_check(blast_output_strain_path):
            parse_strain = parse_best_result_blast (blast_output_strain_path, 
                                    identity_cutoff=95, 
                                    coverage_cutoff=90,
                                    subject_cov_cutoff=90, 
                                    all_hits=False)
            logging.info(f'Mapped {len(parse_strain)} genes to strain-specific UniProt IDs')
            print(f'Mapped {len(parse_strain)} genes to strain-specific UniProt IDs')
        else:
            parse_strain = {}
            logging.warning(f'No strain-specific BLAST results found. Continuing with species-level data only.')
            print(f'WARNING: No strain-specific BLAST results found. Continuing with species-level data only.')
     
        # 3) Map with IDs within the specie
        if files.file_check(blast_output_species_rest_path):
            parse_rest = parse_best_result_blast (blast_output_species_rest_path, 
                                    identity_cutoff=95, 
                                    coverage_cutoff=90, 
                                    subject_cov_cutoff=90,
                                    all_hits=False)
        else:
            logging.error(f'No species-level REST BLAST results found. Cannot proceed with mapping.')
            raise FileNotFoundError(f'{blast_output_species_rest_path} not found.')

        # Merge mapping results

        map_results = {}

        all_locus_tags = set(metadata.ref_gbk_locus(output_path, organism_name))
        for locus_tag in all_locus_tags:
            if locus_tag in parse_pdb:
                map_results[locus_tag] = parse_pdb[locus_tag]
            elif locus_tag in parse_strain:
                map_results[locus_tag] = parse_strain[locus_tag]
            elif locus_tag in parse_rest:
                map_results[locus_tag] = parse_rest[locus_tag]
            else:
                map_results[locus_tag] = None
                print(f'No UniProt ID found for {locus_tag}')
        
        files.dict_to_json(uniprot_dir, f'uniprot_{organism_name}_id_mapping.json', map_results)
    else:
        map_results = files.json_to_dict(proteome_ids_file)
        print(f'IDs file in {proteome_ids_file}.')
    
    return map_results

def parse_resolution(res_str):
    """
    Converts resolution string to float (in Angstroms).
    """
    if not res_str:
        return None
    try:
        return float(str(res_str).split()[0])
    except Exception:
        return None

def parse_chain_string(chains_str):
    """
    Converts chain string from UniProt into list of (chain_id, start, end) tuples.
    
    Handles multiple formats from UniProt PDB chain annotations:
    - Single chain: "A=1-139" → [('A', 1, 139)]
    - Homooligomer (identical chains): "A/B/C=1-139" → [('A', 1, 139)]  # Only first chain
    - Fragmented protein (different subunits): "A=24-193, B=217-762" → [('A', 24, 193), ('B', 217, 762)]  # ALL chains
        Examples: Different chains: Uniprot ID Q9Y251 and PDB ID 5E9C. Same chain: Uniprot ID Q9Y265 and PDB ID 6K0R. 
    - Mixed format: "A/B=27-512, C/P=528-536" → [('A', 27, 512), ('C', 528, 536)]  # First from each group
    - Chain without range: "A" → [('A', None, None)]
    
    Strategy:
    - For chains separated by "/" (e.g., "A/B/C"): These are identical copies, select FIRST only
    - For chains separated by "," (e.g., "A=..., B=..."): These are different subunits, keep ALL
    
    :param chains_str: Chain string from UniProt (e.g., "A/B=1-100, C=101-200")
    :return: List of (chain_id, start, end) tuples representing unique functional chains.
    """

    def range_len(start, end):
        if start is None or end is None:
            return 0
        return max(0, end - start + 1)

    def overlap_len(a_start, a_end, b_start, b_end):
        if a_start is None or a_end is None or b_start is None or b_end is None:
            return 0
        return max(0, min(a_end, b_end) - max(a_start, b_start) + 1)

    def has_significant_overlap(frags, overlap_threshold=0.3):
        for i in range(len(frags)):
            for j in range(i + 1, len(frags)):
                _, a_start, a_end = frags[i]
                _, b_start, b_end = frags[j]
                ov = overlap_len(a_start, a_end, b_start, b_end)
                if ov <= 0:
                    continue
                len_a = range_len(a_start, a_end)
                len_b = range_len(b_start, b_end)
                denom = min(len_a, len_b) if min(len_a, len_b) > 0 else 0
                if denom and (ov / denom) >= overlap_threshold:
                    return True
        return False

    def pick_longest_fragment(frags):
        best = None
        best_len = -1
        for frag in frags:
            _, start, end = frag
            length = range_len(start, end)
            if length > best_len:
                best_len = length
                best = frag
        return [best] if best else frags


    if not chains_str:
        return []

    result = []
    
    # Split by comma first to handle different subunits 
    subunits = [s.strip() for s in str(chains_str).split(',')]
    
    for subunit in subunits:
        if not subunit:
            continue
            
        # Check if there's an equals sign (chain=range format)
        if '=' in subunit:
            chain_part, range_part = subunit.split('=', 1)
            chain_part = chain_part.strip()
            range_part = range_part.strip()
            
            # Handle multiple chains with same range (A/B/C=1-139)
            # These are identical - select FIRST chain only
            if '/' in chain_part:
                chains = [c.strip() for c in chain_part.split('/')]
                chain_id = chains[0]  # Select first chain from homooligomer
                print(f"    Homooligomer detected: '{chain_part}' → selecting chain {chain_id}")
            else:
                chain_id = chain_part
            
            # Parse range
            if '-' in range_part:
                try:
                    start_str, end_str = range_part.split('-', 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                except ValueError:
                    print(f"    Warning: Could not parse range '{range_part}', using None")
                    start = end = None
            else:
                # Single position
                try:
                    start = int(range_part.strip())
                    end = start  # Single residue
                except ValueError:
                    print(f"    Warning: Could not parse position '{range_part}', using None")
                    start = end = None
        else:
            # No range specified, just chain ID (may have slashes)
            if '/' in subunit:
                chains = [c.strip() for c in subunit.split('/')]
                chain_id = chains[0]
                print(f"    Multiple chains without range: '{subunit}' → selecting chain {chain_id}")
            else:
                chain_id = subunit.strip()
            start = end = None
        
        result.append((chain_id, start, end))
    
    if len(result) > 1 and has_significant_overlap(result, overlap_threshold=0.5):
        result = pick_longest_fragment(result)

    return result

def compute_coverage(start, end, seq_len):
    """
    Calculates coverage percentage given start, end, and sequence length.
    coverage = (end - start + 1) / seq_len * 100
    """
    if start is None or end is None or seq_len <= 0:
        return None
    covered = max(0, end - start + 1)
    return (covered / seq_len) * 100.0

def collect_structures_for_uniprot(uniprot_id, uni_info, resolution_cutoff = 3.5, coverage_cutoff = 40.0):
    """
    Given a Uniprot ID and its info dict from Uniprot,
    collects all structure entries (PDB and AlphaFold) and returns
    a list of dicts with structure information.
    
    If protein is fragmented in multiple chains, stores ALL chain IDs
    in the 'chain' field as a semicolon-separated string.
    
    :param uniprot_id: Uniprot accession ID.
    :param uni_info: Dict with Uniprot info.
    :param resolution_cutoff: Resolution (Å) above which AlphaFold is also added alongside PDB.
    :param coverage_cutoff: Minimum coverage (%) to consider a structure valid.
    :return: List of dicts with structure information.
    """

    if resolution_cutoff is None:
        logging.warning("  [WARNING] No resolution cutoff provided, using default of 3.5 Å.")
        resolution_cutoff = 3.5
    if coverage_cutoff is None:
        logging.warning("  [WARNING] No coverage cutoff provided, using default of 40%.")
        coverage_cutoff = 40.0

    seq = uni_info.get("Sequence", "")
    seq_len = len(seq)

    rows = []

    # --- PDBs ---
    pdb_entries = uni_info.get("PDB_id")
    good_pdb = 0  # Track if any PDB passes cutoffs

    if pdb_entries:

        best_by_id = {}

        for entry in pdb_entries:
            if not isinstance(entry, dict):
                continue
            pdb_id = entry.get("ID")
            if not pdb_id:
                continue

            existing = best_by_id.get(pdb_id, {})

            merged = dict(existing)
            merged.update({k: v for k, v in entry.items() if v is not None})
            best_by_id[pdb_id] = merged

        for pdb_id, entry in best_by_id.items():
            has_good_resolution_pdb = False
            has_good_coverage_pdb = False

            method = entry.get("method")
            resolution_str = entry.get("resolution")
            chains_str = entry.get("chains")

            resolution = parse_resolution(resolution_str)
            chain_info_list = parse_chain_string(chains_str)

            # Calculate correct coverage for fragmented proteins or single chains
            if chain_info_list:
                if len(chain_info_list) > 1:
                    
                    start = end = None  # Not a single continuous range

                    # Multiple different subunits
                    chain_ids = []
                    chain_lens = []
                    chain_starts = []
                    chain_ends = []
                    for chain_id, ch_start, ch_end in chain_info_list:
                        chain_starts.append(ch_start)
                        chain_ends.append(ch_end)
                        chain_ids.append(chain_id)
                        chain_lens.append((ch_end - ch_start + 1) if ch_start is not None and ch_end is not None else 0)
                    
                    coverage = sum(chain_lens) / seq_len * 100.0 if seq_len > 0 else None
                    if coverage > 100.0:
                        coverage = 100.0
                    start = min([s for s in chain_starts if s is not None], default=None)
                    end = max([e for e in chain_ends if e is not None], default=None)

                    #Remove if repeated chain IDs
                    chain_ids = list(set(chain_ids))
                    if chain_ids and len(chain_ids) > 1:
                        chain_id_str = ';'.join(chain_ids)
                    else:
                        chain_id_str = chain_ids[0]
                    
                    print(f"Protein fragmented detected for {pdb_id}: chains {chain_id_str}")

                else:
                    # Single chain or homooligomer
                    chain_id_str = chain_info_list[0][0]
                    start, end = chain_info_list[0][1], chain_info_list[0][2]
                    coverage = compute_coverage(start, end, seq_len)
            else:
                chain_id_str = None
                start = end = None
                coverage = None

            # Check if this PDB passes cutoffs (with the correct coverage)
            if resolution is not None and resolution <= resolution_cutoff:
                has_good_resolution_pdb = True
            
            if coverage is not None and coverage >= coverage_cutoff:
                has_good_coverage_pdb = True

            if has_good_resolution_pdb and has_good_coverage_pdb:
                good_pdb += 1            

            rows.append({
                "uniprot_id": uniprot_id,
                "structure_type": "PDB",
                "structure_id": pdb_id,
                "method": method,
                "resolution": resolution,
                "chain": chain_id_str,  # Can be "A;B;C" for fragmented proteins
                "residue_range": f"{start}-{end}" if start is not None and end is not None else None,
                "coverage": coverage,
                "sequence_length": seq_len,
                "is_reference": False,
            })

        # Add AlphaFold only if NO PDB passed the resolution/coverage cutoff
        if good_pdb == 0:
            af_id = uni_info.get("AlphaFoldDB")
            if not af_id:
                print(f"  [INFO] No AlphaFoldDB ID in UniProt for {uniprot_id}, will attempt direct AlphaFold download")
                af_id = uniprot_id  # Use UniProt ID as structure ID for fallback

            rows.append({
                "uniprot_id": uniprot_id,
                "structure_type": "AlphaFold",
                "structure_id": af_id,
                "method": "AlphaFold",
                "resolution": None,
                "chain": "A",
                "residue_range": f"1-{seq_len}" if seq_len > 0 else None,
                "coverage": 100.0 if seq_len > 0 else None,
                "sequence_length": seq_len,
                "is_reference": False,
            })
    else:
        # --- AlphaFold ---
        af_id = uni_info.get("AlphaFoldDB")
        if af_id:
            rows.append({
                "uniprot_id": uniprot_id,
                "structure_type": "AlphaFold",
                "structure_id": af_id,
                "method": "AlphaFold",
                "resolution": None,
                "chain": "A",
                "residue_range": f"1-{seq_len}" if seq_len > 0 else None,
                "coverage": 100.0 if seq_len > 0 else None,
                "sequence_length": seq_len,
                "is_reference": False,
            })
        else:
            # No AlphaFoldDB ID in UniProt, but we can still try to download from AlphaFold
            # using the UniProt ID directly (fallback mechanism)
            print(f"  [INFO] No AlphaFoldDB ID in UniProt for {uniprot_id}, will attempt direct AlphaFold download")
            rows.append({
                "uniprot_id": uniprot_id,
                "structure_type": "AlphaFold",
                "structure_id": uniprot_id,  # Use UniProt ID as structure ID for fallback
                "method": "AlphaFold",
                "resolution": None,
                "chain": "A",
                "residue_range": f"1-{seq_len}" if seq_len > 0 else None,
                "coverage": 100.0 if seq_len > 0 else None,
                "sequence_length": seq_len,
                "is_reference": False,
            })

    return rows

def select_reference_structure(structs, resolution_cutoff=3.5, coverage_cutoff=40.0):
    """
    Given a list of structure dicts (from collect_structures_for_uniprot),
    selects the best structure to use as reference according to new criteria:
    
    Reference structure have BOTH:
      - Resolution < resolution_cutoff (default 3.5Å)
      - Coverage > coverage_cutoff (default 40%)
    
    Selection priority from PDB structures that pass both cutoffs.
    Always X-ray has priority over EM:
      1) X-ray or EM with res <= 2Å → pick highest coverage (tie-break by lowest resolution)
      2) X-ray or EM with res 2-2.5Å → pick highest coverage (tie-break by lowest resolution)
      3) X-ray or EM with res 2.5-3.5Å → prefer coverage > 70%, then pick best resolution
    
    If no PDB passes cutoffs:
      4) Use AlphaFold if available
      5) If no AlphaFold in dict, use UniProt ID as fallback
    
    :param structs: List of structure dicts.
    :param resolution_cutoff: Maximum resolution (Å) to consider (default 3.5).
    :param coverage_cutoff: Minimum coverage (%) to consider (default 40).
    :return: Index of selected structure, or None.
    """
    if not structs:
        return None

    def method_class(s):
        """
        Classify method into 'xray', 'em', 'alphafold', or 'other'.
        """
        m = (s.get("method") or "").lower()
        if "x-ray" in m or "xray" in m or "x-ray diffraction" in m:
            return "xray"
        if "em" in m or "electron microscopy" in m:
            return "em"
        if "alphafold" in m:
            return "alphafold"
        return "other"

    # Separate structures by type
    pdb_xray_idx = []
    pdb_em_idx = []
    alphafold_idx = []

    for i, s in enumerate(structs):
        mclass = method_class(s)
        stype = s.get("structure_type")
        if stype == "PDB":
            if mclass == "xray":
                pdb_xray_idx.append(i)
            elif mclass == "em":
                pdb_em_idx.append(i)
        elif stype == "AlphaFold":
            alphafold_idx.append(i)

    # Filter PDB structures that pass BOTH cutoffs (resolution AND coverage)
    def passes_cutoffs(idx):
        s = structs[idx]
        res = s.get("resolution")
        cov = s.get("coverage")
        if res is None or cov is None:
            return False
        return res <= resolution_cutoff and cov >= coverage_cutoff

    eligible_xray = [i for i in pdb_xray_idx if passes_cutoffs(i)]
    eligible_em = [i for i in pdb_em_idx if passes_cutoffs(i)]
    eligible_pdb = eligible_xray + eligible_em

    if not eligible_pdb:
        # No PDB passes cutoffs, use AlphaFold if available
        if alphafold_idx:
            return alphafold_idx[0]
        # If no AlphaFold, return None (caller will handle UniProt ID fallback)
        return None

    # Categorize eligible PDB structures by resolution range
    ultra_high_res = []  # res <= 2Å
    high_res = []        # 2Å < res <= 2.5Å
    good_res = []        # 2.5Å < res <= resolution_cutoff

    for idx in eligible_pdb:
        res = structs[idx].get("resolution")
        if res <= 2.0:
            ultra_high_res.append(idx)
        elif res <= 2.5:
            high_res.append(idx)
        else:
            good_res.append(idx)

    # 1) Prefer X-ray < 2Å with highest coverage (tie-break by lowest resolution)
    ultra_high_xray = [i for i in ultra_high_res if i in eligible_xray]
    if ultra_high_xray:
        # Pick highest coverage, then lowest resolution
        best = max(ultra_high_xray, key=lambda i: (structs[i].get("coverage") or 0, -structs[i].get("resolution") or 0))
        return best

    # 2) If no X-ray < 2Å, prefer EM < 2Å with highest coverage (tie-break by lowest resolution)
    ultra_high_em = [i for i in ultra_high_res if i in eligible_em]
    if ultra_high_em:
        # Pick highest coverage, then lowest resolution
        best = max(ultra_high_em, key=lambda i: (structs[i].get("coverage") or 0, -structs[i].get("resolution") or 0))
        return best

    # 3) If no structures < 2Å, check 2-2.5Å range → pick highest coverage (tie-break by lowest resolution), X-ray first, then EM
    high_res_xray = [i for i in high_res if i in eligible_xray]
    if high_res_xray:
        best = max(high_res_xray, key=lambda i: (structs[i].get("coverage") or 0, -structs[i].get("resolution") or 0))
        return best
    
    high_res_em = [i for i in high_res if i in eligible_em]
    if high_res_em:
        best = max(high_res_em, key=lambda i: (structs[i].get("coverage") or 0, -structs[i].get("resolution") or 0))
        return best

    # 4) If no structures <= 2.5Å, use any eligible PDB 2.5-3.5Å → prefer coverage > 70%, then pick best resolution (X-ray first, then EM)
    good_res_xray = [i for i in good_res if i in eligible_xray]
    if good_res_xray:
        # Prefer structures with coverage > 70% if available
        high_cov_xray = [i for i in good_res_xray if structs[i].get("coverage", 0) > 70]
        if high_cov_xray:
            best = min(high_cov_xray, key=lambda i: structs[i].get("resolution") or float("inf"))
        else:
            best = min(good_res_xray, key=lambda i: structs[i].get("resolution") or float("inf"))
        return best
    
    good_res_em = [i for i in good_res if i in eligible_em]
    if good_res_em:
        # Prefer structures with coverage > 70% if available
        high_cov_em = [i for i in good_res_em if structs[i].get("coverage", 0) > 70]
        if high_cov_em:
            best = min(high_cov_em, key=lambda i: structs[i].get("resolution") or float("inf"))
        else:
            best = min(good_res_em, key=lambda i: structs[i].get("resolution") or float("inf"))
        return best

    # Fallback (shouldn't reach here if eligible_pdb is not empty)
    if alphafold_idx:
        return alphafold_idx[0]
    
    return None

def create_subfolder_structures(output_path, organism_name):
    """
    Create structures subfolder within structure folder.
    Create one folder per locus_tag and one per UniProt ID.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    proteome_ids_file = os.path.join(structure_dir, 'uniprot_files', f'uniprot_{organism_name}_id_mapping.json')

    if files.file_check(proteome_ids_file):
        print(f'Creating subfolders for structures in {structure_dir}...')
        map_results = files.json_to_dict(proteome_ids_file)
        
        for locus_tag in map_results.keys():
            locus_tag_dir = os.path.join(structure_dir, locus_tag)
            os.makedirs(locus_tag_dir, exist_ok=True)

            uniprot_ids = map_results[locus_tag]
            if uniprot_ids:
                if isinstance(uniprot_ids, list):
                    for uniprot_id in uniprot_ids:
                        uniprot_dir = os.path.join(locus_tag_dir, uniprot_id)
                        os.makedirs(uniprot_dir, exist_ok=True)
                else:
                    uniprot_dir = os.path.join(locus_tag_dir, uniprot_ids)
                    os.makedirs(uniprot_dir, exist_ok=True)
    else:
        raise FileNotFoundError(f'{proteome_ids_file} not found.')

def create_summary_structure_table(batch_annotations, mapping_dict, locus_tag, resolution_cutoff = 3.5, coverage_cutoff = 40.0):
    """
    Create a summary table with structure information for a locus_tag.
    Only ONE structure will be marked as reference across all UniProt IDs.
    
    Priority for reference selection:
    1. Best structure from first UniProt ID with PDB structures
    2. If no PDB in first UniProt, check AlphaFold
    3. If first UniProt has no structures, check next UniProt IDs
    
    :param mapping_dict: Dictionary mapping locus_tags to UniProt IDs.
    :param batch_annotations: Dictionary with UniProt annotations for all UniProt IDs.
    :param locus_tag: Locus tag to create summary for.
    :param resolution_cutoff: Resolution (Å) above to consider a PDB valid reference.
    :param coverage_cutoff: Minimum coverage (%) to consider a structure valid.

    :return: DataFrame with structure summary.
    """
    uniprot_id = None

    summary_data = []
    uniprot_ids = mapping_dict.get(locus_tag)

    if uniprot_ids:
        # Normalize to list
        if not isinstance(uniprot_ids, list):
            uniprot_ids = [uniprot_ids]
        
        # Collect all structures from all UniProt IDs
        for uniprot_id in uniprot_ids:    
            if uniprot_id in batch_annotations:
                uni_info = batch_annotations[uniprot_id]
                structures_info = collect_structures_for_uniprot(uniprot_id, uni_info, resolution_cutoff, coverage_cutoff)
                for struct in structures_info:
                    summary_data.append(struct)
            else:
                print(f'  Warning: No annotations found for UniProt ID {uniprot_id}')
        

    if summary_data:
        # Select ONE reference structure across ALL UniProt IDs for this locus_tag
        ref_idx = select_reference_structure(summary_data, resolution_cutoff, coverage_cutoff)
        if ref_idx is not None:
            summary_data[ref_idx]["is_reference"] = True
            print(f'  Selected reference: {summary_data[ref_idx]["structure_id"]} (UniProt: {summary_data[ref_idx]["uniprot_id"]})')
        else:
            print(f'  Warning: No reference structure selected for {locus_tag}.')

        summary_df = pd.DataFrame(summary_data)
    else:
        summary_data.append({
        "locus_tag": locus_tag,
        "uniprot_id": uniprot_id,
        "structure_type": "No structure found",
        "structure_id": "NONE",
        "method": None,
        "resolution": None,
        "chain": None,
        "residue_range": None,
        "coverage": None,
        "sequence_length": None,
        "is_reference": False
         })

        print(f'  No structure data found for {locus_tag}.')
        summary_df = pd.DataFrame(summary_data)

    return summary_df

def create_summary_structure_file(output_path, organism_name, resolution_cutoff= 3.5, coverage_cutoff=40.0):

    """
    Create a TSV summary file with structure information for each locus_tag.
    The table includes:
    - uniprot_id
    - AlphaFold ID
    - PDB IDs

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param resolution_cutoff: Resolution (Å) above to consider a PDB valid reference.
    :param coverage_cutoff: Minimum coverage (%) to consider a structure valid.

    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    uniprot_files_dir = os.path.join(structure_dir, 'uniprot_files')
    proteome_ids_file = os.path.join(uniprot_files_dir, f'uniprot_{organism_name}_id_mapping.json')

    if not files.file_check(proteome_ids_file):
        raise FileNotFoundError(f'{proteome_ids_file} not found.')

    map_results = files.json_to_dict(proteome_ids_file)

    print(f'Creating structure summary table for each locus_tag in {structure_dir}...')

    all_uniprot_ids = []

    for uniprot_ids in map_results.values():
        if isinstance(uniprot_ids, list):
            all_uniprot_ids.extend(uniprot_ids)
        elif uniprot_ids:
            all_uniprot_ids.append(uniprot_ids)

    # Remove None and duplicates
    all_uniprot_ids = [uid for uid in all_uniprot_ids if uid]
    all_uniprot_ids = list(set(all_uniprot_ids))

    # Fetch all annotations at once
    if not files.file_check(os.path.join(structure_dir, 'uniprot_files', f'uniprot_{organism_name}_annotations.json')):
        print(f'Fetching UniProt annotations for {len(set(all_uniprot_ids))} unique UniProt IDs...')
        batch_annotations = uniprot_protein_annotations_batch(list(set(all_uniprot_ids)))
        files.dict_to_json(uniprot_files_dir, f'uniprot_{organism_name}_annotations.json', batch_annotations)
    else:
        batch_annotations = files.json_to_dict(os.path.join(uniprot_files_dir, f'uniprot_{organism_name}_annotations.json'))
        print(f'UniProt annotations file found for {len(batch_annotations)} UniProt IDs.')

    for locus_tag in tqdm(map_results.keys(), desc='Locus tags'):
        
        summary_table_path = os.path.join(structure_dir, locus_tag, f"{locus_tag}_structure_summary.tsv")

        if not files.file_check(summary_table_path):
            
            summary_df = create_summary_structure_table(batch_annotations, map_results, locus_tag, resolution_cutoff, coverage_cutoff)
            if not summary_df.empty:
                # Ensure structure_id is stored as string to prevent scientific notation issues
                summary_df['structure_id'] = summary_df['structure_id'].astype(str)
                summary_df.to_csv(summary_table_path, sep='\t', index=False, quoting=csv.QUOTE_NONNUMERIC)
            else:
                print(f'No structure data found for {locus_tag}')

        else:
            print(f'Structure summary table already exists for {locus_tag}.')


##  ------------------- Download structures functions ------------------- ## 
def get_structure_PDB (output_path, PDB_id):
    """
    Download structure from PDB. Returns True if successful.
    
    :param output_path: Output directory path.
    :param PDB_id: ID of PDB structure.

    :return: True if successful, False otherwise.
    """
    res = False
    file_path = os.path.join(output_path, f"PDB_{PDB_id}.pdb")

    if not files.file_check(file_path):

        pdb_url = f"https://files.rcsb.org/download/{PDB_id}.pdb"

        for attempt in range(3):
            try:
                response = requests.get(pdb_url, timeout=30)
                if response.status_code == 200:
                    # Verify we got content
                    if len(response.content) > 0:
                        with open(file_path, 'wb') as file:
                            file.write(response.content)
                        # Verify file was written successfully
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                            print(f"Downloaded {PDB_id}.pdb.")
                            res = True
                            break
                        else:
                            print(f"Warning: File {file_path} not written correctly, retrying...")
                    else:
                        print(f"Warning: Empty content received for {PDB_id}.pdb")
                elif response.status_code == 404:
                    # 404 means PDB format doesn't exist, no point retrying
                    print(f"PDB format not available for {PDB_id} (404).")
                    break
                else:
                    print(f"Failed to download .pdb for {PDB_id}, status code: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f'Failed to download .pdb for {PDB_id}, attempt {attempt + 1}/3: {e}')
            
            if attempt == 2 and not res:
                print(f"Failed to download .pdb for {PDB_id} after 3 attempts.")
    else:
        print(f"PDB file {file_path} already exists.")
        res = True
    return res

def get_structure_CIF (output_path, PDB_id):
    """
    Download structure from PDB in CIF format. Returns True if successful.
    
    :param output_path: Output directory path.
    :param PDB_id: ID of PDB structure.

    :return: True if successful, False otherwise.
    """
    res = False
    file_path = os.path.join(output_path, f"PDB_{PDB_id}.cif")

    if not files.file_check(file_path):

        pdb_url = f"https://files.rcsb.org/download/{PDB_id}.cif"

        for attempt in range(3):
            try:
                response = requests.get(pdb_url, timeout=30)
                if response.status_code == 200:
                    # Verify we got content
                    if len(response.content) > 0:
                        with open(file_path, 'wb') as file:
                            file.write(response.content)
                        # Verify file was written successfully
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                            print(f"Downloaded {PDB_id}.cif.")
                            res = True
                            break
                        else:
                            print(f"Warning: File {file_path} not written correctly, retrying...")
                    else:
                        print(f"Warning: Empty content received for {PDB_id}.cif")
                elif response.status_code == 404:
                    # 404 means structure doesn't exist at all
                    print(f"Structure {PDB_id} not found (404).")
                    break
                else:
                    print(f"Failed to download .cif for {PDB_id}, status code: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f'Failed to download .cif for {PDB_id}, attempt {attempt + 1}/3: {e}')
            
            if attempt == 2 and not res:
                print(f"Failed to download .cif for {PDB_id} after 3 attempts.")
    else:
        print(f"CIF file {file_path} already exists.")
        res = True

    return res

def get_structure_alphafold(output_path, uniprot_id):
    """
    Download structure from AlphaFold. Returns True if successful.
    
    :param output_path: Output directory path.
    :param uniprot_id: ID of UniProt with AlphaFold structure.

    :return: True if successful, False otherwise.
    """

    res = False
    file_path = os.path.join(output_path, f"AF_{uniprot_id}.pdb")

    if not files.file_check(file_path):

        alphafold_url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v6.pdb"

        for attempt in range(3):
            try: 
                response = requests.get(alphafold_url, timeout=30)
                if response.status_code == 200:
                    # Verify we got content
                    if len(response.content) > 0:
                        with open(file_path, 'wb') as file:
                            file.write(response.content)
                        # Verify file was written successfully
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                            print(f"Downloaded AlphaFold model {uniprot_id}.")
                            res = True
                            break
                        else:
                            print(f"Warning: File {file_path} not written correctly, retrying...")
                    else:
                        print(f"Warning: Empty content received for AlphaFold {uniprot_id}")
                elif response.status_code == 404:
                    # 404 means AlphaFold prediction doesn't exist for this UniProt ID
                    print(f"AlphaFold prediction not available for {uniprot_id} (404).")
                    marker_path = os.path.join(output_path, f".no_af_{uniprot_id}")
                    with open(marker_path, "w") as fh:
                        fh.write("404")
                    break

                else:
                    print(f"Failed to download AlphaFold for {uniprot_id}, status code: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"Failed to download AlphaFold prediction for {uniprot_id}, attempt {attempt + 1}/3: {e}")
            
            if attempt == 2 and not res:
                print(f"Failed to download AlphaFold prediction for {uniprot_id} after 3 attempts.")
    else:
        print(f"AlphaFold file {file_path} already exists.")
        res = True
    return res

def download_single_structure(structure_dir, locus_tag):
    """
    Download structures for a single locus_tag based on the summary table.
    Priority: Download .pdb if available, otherwise download .cif (for cryo-EM structures).
    :param structure_dir: Directory of the structures.
    :param locus_tag: Locus tag identifier.
    
    """

    summary_table_path = os.path.join(structure_dir, locus_tag, f"{locus_tag}_structure_summary.tsv")

    if files.file_check(summary_table_path):
        # Read structure_id as string to prevent scientific notation (e.g., 3E59 -> 3e+59)
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        summary_df = pd.read_csv(summary_table_path, sep='\t', dtype={'structure_id': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])

        uniprot_ids = summary_df['uniprot_id'].unique()

        for uniprot_id in uniprot_ids:

            if uniprot_id and isinstance(uniprot_id, str):
                    
                uniprot_dir = os.path.join(structure_dir, locus_tag, uniprot_id)

                struct_rows = summary_df[summary_df['uniprot_id'] == uniprot_id]

                for _, row in struct_rows.iterrows():
                    struct_type = row['structure_type']
                    struct_id = row['structure_id']

                    if struct_type == 'PDB':
                        # Define file paths
                        pdb_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.pdb")
                        cif_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.cif")
                        
                        # Check if we already have a valid structure file
                        # Use try-except to handle potential race conditions or filesystem issues
                        try:
                            pdb_exists = files.file_check(pdb_file_path) and os.path.getsize(pdb_file_path) > 0
                        except OSError:
                            pdb_exists = False
                        
                        try:
                            cif_exists = files.file_check(cif_file_path) and os.path.getsize(cif_file_path) > 0
                        except OSError:
                            cif_exists = False
                        
                        if pdb_exists or cif_exists:
                            continue
                        
                        # Try PDB format first
                        success_pdb = get_structure_PDB(uniprot_dir, struct_id)
                        
                        # If PDB fails, try CIF (common for cryo-EM structures)
                        if not success_pdb:
                            print(f"  PDB format not available for {struct_id}, trying CIF format...")
                            success_cif = get_structure_CIF(uniprot_dir, struct_id)
                            
                            if not success_cif:
                                print(f"  Warning: Could not download {struct_id} in either PDB or CIF format.")

                    elif struct_type == 'AlphaFold':
                        # Check and download AlphaFold structure
                        # Note: This handles both cases:
                        # 1. AlphaFoldDB ID from UniProt API
                        # 2. Fallback attempt using UniProt ID directly when no AlphaFoldDB ID was found
                        af_file_path = os.path.join(uniprot_dir, f"AF_{uniprot_id}.pdb")
                        
                        # Check if we already have a valid AlphaFold file
                        try:
                            af_exists = files.file_check(af_file_path) and os.path.getsize(af_file_path) > 0
                        except OSError:
                            af_exists = False
                        
                        if not af_exists:
                            # Download using UniProt ID (works for both explicit and fallback cases)
                            success_af = get_structure_alphafold(uniprot_dir, uniprot_id)
                            if not success_af:
                                print(f"  Warning: Could not download AlphaFold model for {uniprot_id}.")
        
        # Remove AlphaFold rows only when we have an explicit 404 marker
        af_rows = summary_df[summary_df['structure_type'] == 'AlphaFold']
        if not af_rows.empty:
            drop_idx = []
            for idx, row in af_rows.iterrows():
                af_uniprot_id = row['uniprot_id']
                if not af_uniprot_id or not isinstance(af_uniprot_id, str) or pd.isna(af_uniprot_id):
                    continue

                af_uniprot_dir = os.path.join(structure_dir, locus_tag, af_uniprot_id)
                af_file_path = os.path.join(af_uniprot_dir, f"AF_{af_uniprot_id}.pdb")
                marker_path = os.path.join(af_uniprot_dir, f".no_af_{af_uniprot_id}")

                try:
                    af_exists = files.file_check(af_file_path) and os.path.getsize(af_file_path) > 0
                except OSError:
                    af_exists = False

                if (not af_exists) and files.file_check(marker_path):
                    drop_idx.append(idx)

            if drop_idx:
                summary_df = summary_df.drop(index=drop_idx)
                summary_df.to_csv(summary_table_path, sep='\t', index=False, quoting=csv.QUOTE_NONNUMERIC)
                print(f'Updated structure summary table for {locus_tag} after removing unavailable AlphaFold entries.')

    else:
        print(f'Structure summary table not found for {locus_tag}, skipping download check.')

def download_structures(output_path, organism_name):

    """
    Download structures for each locus_tag based on the summary table.
    
    Priority: Download .pdb if available, otherwise download .cif (for cryo-EM structures).
    
    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.

    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in tqdm(all_locus_tags, desc='Locus tags'):
        try:
            download_single_structure(structure_dir, locus_tag)
        except Exception as e:
            logging.error(f"Error downloading structures for {locus_tag}: {e}")
            
def extract_chain_from_pdb(pdb_file, chain_ids, output_file):
    """
    Extracts one or more specific chains from a PDB file using Biopython
    into a single output file.

    :param pdb_file: Path to the input PDB file.
    :param chain_ids: Single chain ID (str) or list of chain IDs to extract.
    :param output_file: Path to the output PDB file where the extracted chain(s) will be saved.
    """

    # Normalize to list
    if isinstance(chain_ids, str):
        if ';' in chain_ids:
            chain_ids = [c.strip() for c in chain_ids.split(';')]
        else:
            chain_ids = [chain_ids]
    
    class MultiChainSelect(Select):
        """
        Biopython Select subclass to filter multiple chains.
        
        Accepts chains whose IDs match any in the provided list.
        Used for extracting different subunits.
        """
        def __init__(self, chain_ids: list):
            super().__init__()
            self.chain_ids = [str(c).strip() for c in chain_ids]

        def accept_chain(self, chain) -> bool:
            """Return True if chain ID is in the list of requested chains."""
            return chain.id in self.chain_ids
    
    parser = PDBParser(QUIET=True)

    structure_id = Path(pdb_file).stem or "structure"
    structure = parser.get_structure(structure_id, pdb_file)
    
    # Verify that requested chains exist in the structure
    available_chains = [chain.id for model in structure for chain in model]
    missing_chains = [c for c in chain_ids if c not in available_chains]
    
    if missing_chains:
        print(f"    Warning: Chain(s) {missing_chains} not found in {Path(pdb_file).name}")
        print(f"    Available chains: {available_chains}")
        # Continue with available chains only
        chain_ids = [c for c in chain_ids if c in available_chains]
        if not chain_ids:
            raise ValueError(f"None of the requested chains found in {pdb_file}")

    io = PDBIO()
    io.set_structure(structure)

    selector = MultiChainSelect(chain_ids)
    io.save(output_file, select=selector)
    
    # Verify output file was created and has content
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise IOError(f"Failed to create output file {output_file}")
    
    chains_str = ','.join(chain_ids)
    print(f"    Extracted chain(s) {chains_str} from {Path(pdb_file).name}")

def extract_chain_from_cif(cif_file, chain_ids, output_file):
    """
    Extracts one or more specific chains from a CIF file using Biopython.
    
    This function is similar to extract_chain_from_pdb but works with mmCIF format files,
    which are commonly used for cryo-EM structures.

    :param cif_file: Path to the input CIF file.
    :param chain_ids: Single chain ID (str) or list of chain IDs to extract.
    :param output_file: Path to the output file where the extracted chain(s) will be saved.
                        If multi-character chains are present, output will be in CIF format.
    """
    from Bio.PDB import MMCIFParser, MMCIFIO
    
    # Normalize to list
    if isinstance(chain_ids, str):
        if ';' in chain_ids:
            chain_ids = [c.strip() for c in chain_ids.split(';')]
        else:
            chain_ids = [chain_ids]
    
    class MultiChainSelect(Select):
        """
        Biopython Select subclass to filter multiple chains.
        
        Accepts chains whose IDs match any in the provided list.
        Used for extracting multiple different subunits.
        """
        def __init__(self, chain_ids: list):
            super().__init__()
            self.chain_ids = [str(c).strip() for c in chain_ids]

        def accept_chain(self, chain) -> bool:
            """Return True if chain ID is in the list of requested chains."""
            return chain.id in self.chain_ids
    
    parser = MMCIFParser(QUIET=True)

    structure_id = Path(cif_file).stem or "structure"
    structure = parser.get_structure(structure_id, cif_file)
    
    # Verify that requested chains exist in the structure
    available_chains = [chain.id for model in structure for chain in model]
    missing_chains = [c for c in chain_ids if c not in available_chains]
    
    if missing_chains:
        print(f"    Warning: Chain(s) {missing_chains} not found in {Path(cif_file).name}")
        print(f"    Available chains: {available_chains}")
        # Continue with available chains only
        chain_ids = [c for c in chain_ids if c in available_chains]
        if not chain_ids:
            raise ValueError(f"None of the requested chains found in {cif_file}")

    # Check if any chain ID has more than 1 character (requires CIF output format)
    has_multichar_chains = any(len(str(c)) > 1 for c in chain_ids)
    
    if has_multichar_chains:
        # Use MMCIFIO to preserve multi-character chain IDs
        io = MMCIFIO()
        io.set_structure(structure)
        selector = MultiChainSelect(chain_ids)
        # Ensure output file has .cif extension
        if not output_file.endswith('.cif'):
            output_file = output_file.rsplit('.', 1)[0] + '.cif'
        io.save(output_file, select=selector)
    else:
        # Use PDBIO for single-character chains (standard PDB format)
        io = PDBIO()
        io.set_structure(structure)
        selector = MultiChainSelect(chain_ids)
        io.save(output_file, select=selector)
    
    # Verify output file was created and has content
    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        raise IOError(f"Failed to create output file {output_file}")
    
    chains_str = ','.join(chain_ids)
    print(f"    Extracted chain(s) {chains_str} from {Path(cif_file).name} (CIF)")

def get_chain_all_pdbs_for_locus(locus_tag, locus_dir):
    """
    For each locus_tag, extract chain(s) from ALL downloaded PDB structures
    listed in the structure summary table (not only the reference one).

    Handles:
    - Single chains (monomers / homooligomers)
    - Multiple chains (fragmented proteins)

    AlphaFold structures are skipped (no chain extraction needed).

    :param locus_tag: Locus tag identifier.
    :param structure_dir: Directory of the structures.
    """

    summary_table_path = os.path.join(
        locus_dir, f"{locus_tag}_structure_summary.tsv"
    )

    if not files.file_check(summary_table_path):
        print(f'  Structure summary table not found for {locus_tag}, skipping.')
        return

    # Keep "NA" as string (valid chain name) instead of treating it as NaN
    summary_df = pd.read_csv(
        summary_table_path, sep='\t', dtype={'structure_id': str},
        keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null']
    )

    # Keep only PDB entries
    pdb_rows = summary_df[summary_df['structure_type'] == 'PDB']

    if pdb_rows.empty:
        print(f'  No PDB structures found for {locus_tag}.')
        return

    for _, row in pdb_rows.iterrows():
        struct_id = row['structure_id']
        chain_field = row['chain']
        uniprot_id = row['uniprot_id']

        if not uniprot_id or not isinstance(uniprot_id, str) or pd.isna(uniprot_id) or uniprot_id.strip() == '':
            print(f"  Warning: Missing UniProt ID for structure {struct_id} in {locus_tag}, skipping.")
            continue

        # Parse chain field
        if not chain_field or pd.isna(chain_field):
            chain_ids = ['A']
            print(f'  Warning: No chain ID for {struct_id} in {locus_tag}, defaulting to A.')
        elif ';' in str(chain_field):
            chain_ids = [c.strip() for c in str(chain_field).split(';')]
        else:
            chain_ids = [str(chain_field)]

        uniprot_dir = os.path.join(locus_dir, uniprot_id)

        if not os.path.isdir(uniprot_dir):
            print(f'  ERROR: UniProt directory {uniprot_dir} not found for {locus_tag}.')
            continue

        pdb_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.pdb")
        cif_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.cif")

        # Build output filename
        if len(chain_ids) > 1:
            if len(chain_ids) <= 5:
                chains_suffix = '_'.join(chain_ids)
            else:
                chains_suffix = f"{chain_ids[0]}_to_{chain_ids[-1]}_multi"
        else:
            chains_suffix = chain_ids[0]

        output_chain_file = os.path.join(
            uniprot_dir, f"PDB_{struct_id}_chain_{chains_suffix}.pdb"
        )

        # Check file validity
        try:
            pdb_valid = files.file_check(pdb_file_path) and os.path.getsize(pdb_file_path) > 0
        except OSError:
            pdb_valid = False

        try:
            cif_valid = files.file_check(cif_file_path) and os.path.getsize(cif_file_path) > 0
        except OSError:
            cif_valid = False

        if pdb_valid:
            if not files.file_check(output_chain_file):
                print(f'  Extracting chain(s) {chain_ids} from PDB {struct_id} ({locus_tag})')
                try:
                    extract_chain_from_pdb(
                        pdb_file_path, chain_ids, output_chain_file
                    )
                except Exception as e:
                    logging.exception(
                        f'Failed to extract chains {chain_ids} from {pdb_file_path}: {e}'
                    )
            else:
                print(f'  Chain file already exists: {output_chain_file}')

        elif cif_valid:
            if not files.file_check(output_chain_file):
                print(f'  Extracting chain(s) {chain_ids} from CIF {struct_id} ({locus_tag})')
                try:
                    extract_chain_from_cif(
                        cif_file_path, chain_ids, output_chain_file
                    )
                except Exception as e:
                    logging.exception(
                        f'Failed to extract chains {chain_ids} from {cif_file_path}: {e}'
                    )
            else:
                print(f'  Chain file already exists: {output_chain_file}')

        else:
            print(
                f'  ERROR: No valid PDB or CIF file for {struct_id} '
                f'in locus_tag {locus_tag}.'
            )

def get_chain_all_pdbs(output_path, organism_name):
    """
    For each locus_tag, extract chain(s) from ALL downloaded PDB structures
    listed in the structure summary table (not only the reference one).

    Handles:
    - Single chains (monomers / homooligomers)
    - Multiple chains (fragmented proteins)

    AlphaFold structures are skipped (no chain extraction needed).

    :param output_path: Directory of the organism output.
    :param organism_name: Name of organism.
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in all_locus_tags:
        locus_dir = os.path.join(structure_dir, locus_tag)

        if not os.path.isdir(locus_dir):
            continue
        
        try:
            get_chain_all_pdbs_for_locus(locus_tag, locus_dir)
        except Exception as e:
            logging.error(f"Error extracting chains for {locus_tag}: {e}")

def get_chain_reference_structure_for_locus (locus_tag, locus_dir):
    """
    For each locus_tag, get the reference structure chain(s) and save to a separate PDB file.
    
    Handles both:
    - Single chains (homooligomers or monomers): extracts one chain
    - Multiple chains (fragmented proteins): extracts ALL functional subunits
    
    IMPORTANT: Only ONE structure should be marked as reference per locus_tag.
    This function extracts the chain(s) from that single reference structure.

    :param locus_tag: Locus tag identifier.
    :param locus_dir: Directory of the locus.
    """
        
    summary_table_path = os.path.join(locus_dir, f"{locus_tag}_structure_summary.tsv")

    if files.file_check(summary_table_path):
        # Read structure_id as string to prevent scientific notation (e.g., 3E59 -> 3e+59)
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        summary_df = pd.read_csv(summary_table_path, sep='\t', dtype={'structure_id': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])

        ref_rows = summary_df[summary_df['is_reference'] == True]

        if ref_rows.empty:
            print(f'  Warning: No reference structure found for locus_tag {locus_tag}.')
            return
        
        if len(ref_rows) > 1:
            print(f'  ERROR: Multiple reference structures found for {locus_tag}. There should be only ONE.')
            print(f'  Found {len(ref_rows)} reference structures. Using first one.')
            ref_row = ref_rows.iloc[0]
        else:
            ref_row = ref_rows.iloc[0]
        
        struct_type = ref_row['structure_type']
        struct_id = ref_row['structure_id']
        chain_field = ref_row['chain']
        uniprot_id = ref_row['uniprot_id']

        if not uniprot_id or not isinstance(uniprot_id, str) or pd.isna(uniprot_id) or uniprot_id.strip() == '':
            print(f"  Warning: Missing UniProt ID for reference structure {struct_id} in {locus_tag}, skipping.")
            return
        
        # Parse chain field - can be single "A" or multiple "A;B;C"
        if not chain_field or pd.isna(chain_field):
            chain_ids = ['A']
            print(f'  Warning: No chain ID specified for {struct_id} in {locus_tag}, defaulting to chain A.')
        elif ';' in str(chain_field):
            # Multiple chains
            chain_ids = [c.strip() for c in str(chain_field).split(';')]
            print(f'  Warning: Multiple chains detected for {locus_tag}: extracting chains {chain_ids}')
        else:
            # Single chain
            chain_ids = [str(chain_field)]
        
        uniprot_dir = os.path.join(locus_dir, uniprot_id)
        
        # Check if uniprot_dir exists
        if not os.path.isdir(uniprot_dir):
            print(f'  ERROR: UniProt directory {uniprot_dir} not found for {locus_tag}.')
            return

        # Only extract chain(s) for PDB structures (AlphaFold doesn't need extraction)
        if struct_type == 'PDB':
            pdb_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.pdb")
            cif_file_path = os.path.join(uniprot_dir, f"PDB_{struct_id}.cif")
            
            # Create filename with chain notation
            # Limit filename length for many chains
            if len(chain_ids) > 1:
                if len(chain_ids) <= 5:  # Reasonable limit
                    chains_suffix = '_'.join(chain_ids)
                else:
                    # For structures with many chains, use compact notation
                    chains_suffix = f"{chain_ids[0]}_to_{chain_ids[-1]}_multi"
            else:
                chains_suffix = chain_ids[0]
                
            output_chain_file = os.path.join(uniprot_dir, f"PDB_{struct_id}_{chains_suffix}_ref.pdb")
            
            # Try PDB format first, then CIF format
            # Verify files exist AND have content (not empty/corrupt)
            try:
                pdb_valid = files.file_check(pdb_file_path) and os.path.getsize(pdb_file_path) > 0
            except OSError:
                pdb_valid = False
            
            try:
                cif_valid = files.file_check(cif_file_path) and os.path.getsize(cif_file_path) > 0
            except OSError:
                cif_valid = False
            
            if pdb_valid:
                if not files.file_check(output_chain_file):
                    print(f'  Extracting chain(s) {chain_ids} from {struct_id} for {locus_tag}')
                    try:
                        extract_chain_from_pdb(pdb_file_path, chain_ids, output_chain_file)
                    except Exception as e:
                        logging.exception(f'Failed to extract chain(s) {chain_ids} from {pdb_file_path}: {e}')
                else:
                    print(f'  Chain file already exists: {output_chain_file}')
            elif cif_valid:
                # Use CIF file if PDB not available (common for cryo-EM)
                if not files.file_check(output_chain_file):
                    print(f'  Extracting chain(s) {chain_ids} from {struct_id} CIF for {locus_tag}')
                    try:
                        extract_chain_from_cif(cif_file_path, chain_ids, output_chain_file)
                    except Exception as e:
                        logging.exception(f'Failed to extract chain(s) {chain_ids} from {cif_file_path}: {e}')
                else:
                    print(f'  Chain file already exists: {output_chain_file}')
            else:
                print(f'  ERROR: Neither PDB nor CIF file found (or files are empty) for {struct_id} in locus_tag {locus_tag}.')
                if files.file_check(pdb_file_path):
                    try:
                        size = os.path.getsize(pdb_file_path)
                        print(f'    Note: {pdb_file_path} exists but is empty (size: {size} bytes)')
                    except OSError:
                        print(f'    Note: {pdb_file_path} exists but size cannot be determined')
                if files.file_check(cif_file_path):
                    try:
                        size = os.path.getsize(cif_file_path)
                        print(f'    Note: {cif_file_path} exists but is empty (size: {size} bytes)')
                    except OSError:
                        print(f'    Note: {cif_file_path} exists but size cannot be determined')
        
        elif struct_type == 'AlphaFold':
            af_file_path = os.path.join(uniprot_dir, f"AF_{uniprot_id}.pdb")
            if not files.file_check(af_file_path):
                print(f'  ERROR: AlphaFold file {af_file_path} not found for locus_tag {locus_tag}.')
    else:
        print(f'  Structure summary table not found for {locus_tag}, skipping chain extraction.')

def get_chain_reference_structure(output_path, organism_name):
    """
    For each locus_tag, get the reference structure chain(s) and save to a separate PDB file.
    Uses get_chain_reference_structure_for_locus for each locus_tag.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)
    
    for locus_tag in all_locus_tags:
        locus_dir = os.path.join(structure_dir, locus_tag)
    
        if not os.path.isdir(locus_dir):
            continue

        try:
            get_chain_reference_structure_for_locus(locus_tag, locus_dir)
        except Exception as e:
            logging.error(f"Error extracting reference structure for {locus_tag}: {e}")

def find_structures_for_locus(locus_dir, colabfold=False, colabfold_all_models=False):
    """
    Find ONLY the reference structure for a given locus_tag directory.
    
    Selection rules (DEFAULT TRACK - PDB/AF priority, CB as fallback only):
    1) Look for PDB reference structures (*_ref.pdb)
       (These are PDB chains extracted by extract_chain_from_pdb)
    2) If no '_ref.pdb' found, use AlphaFold models: files starting with 'AF_'
       (AlphaFold files don't need chain extraction)
    3) If no AlphaFold, use ColabFold models: files starting with 'CB_' if colabfold=True
       (ColabFold models generated locally - only as FALLBACK)
    4) If nothing found, return None
    
    NOTE: When colabfold_all_models=True, this function still returns ONLY the
    reference structure for the default pipeline. CB models are handled separately
    in the parallel ColabFold track.
    
    :param locus_dir: Path to the locus_tag directory.
    :param colabfold: Boolean indicating whether to consider ColabFold models as fallback.
    :param colabfold_all_models: Boolean (ignored here - CB handled separately in parallel track).
    :return: List of paths to structures to use.
    """

    # 1) First priority: Reference structures (*_ref.pdb)
    # Exclude folder pockets
    pdb_files = glob.glob(os.path.join(locus_dir, '**', 'PDB_*.pdb'), recursive=True)
    ref_files = glob.glob(os.path.join(locus_dir, '**', 'PDB*_ref.pdb'), recursive=True)
    ref_files = [f for f in ref_files if 'pockets' not in f.split(os.sep)]
    ref_files = sorted(set(ref_files))
    
    if len(ref_files) > 1:
        print(f"  ERROR: Found {len(ref_files)} '*_ref.pdb' files in {locus_dir}. There should be only ONE reference.")
        print(f"  Files found: {ref_files}")
        print(f"  Using first file: {ref_files[0]}")
        return [ref_files[0]]
    elif len(ref_files) == 1:
        print(f"  Using PDB reference: {ref_files[0]}")
        return [ref_files[0]]
    elif len(ref_files) == 0:
        if len(pdb_files) == 0:
            print(f"  No PDB files found in {locus_dir}. Checking for CIF files...")
        else:
            print(f"  ERROR: Found {len(pdb_files)} PDB files in {locus_dir} but no '*_ref.pdb' file.")
            logging.warning(f" Error with reference structures in {locus_dir}. Please ensure that one PDB structure is marked as reference.")
        cif_files = glob.glob(os.path.join(locus_dir, '**', 'PDB_*.cif'), recursive=True)
        cif_ref_files = glob.glob(os.path.join(locus_dir, '**', 'PDB*_ref.cif'), recursive=True)
        cif_ref_files = [f for f in cif_ref_files if 'pockets' not in f.split(os.sep)]
        cif_ref_files = sorted(set(cif_ref_files))
        if len(cif_ref_files) > 1:
            print(f"  ERROR: Found {len(cif_ref_files)} '*_ref.cif' files in {locus_dir}. There should be only ONE reference.")
            print(f"  Files found: {cif_ref_files}")
            print(f"  Using first file: {cif_ref_files[0]}")
            return [cif_ref_files[0]]
        elif len(cif_ref_files) == 1:   
            print(f"  Using CIF reference: {cif_ref_files[0]}")
            return [cif_ref_files[0]]
        elif len(cif_ref_files) == 0 and len(cif_files) > 1:
            print(f"  ERROR: Found {len(cif_files)} CIF files in {locus_dir} but no '*_ref.cif' file.")
            logging.warning(f" Error with reference structures in {locus_dir}. Please ensure that one CIF structure is marked as reference.")
        elif len(cif_ref_files) == 0 and len(cif_files) == 0:
            print(f"  No CIF files found in {locus_dir}. Checking for AlphaFold models...")
    
    # 2) Second priority: AlphaFold models (if no PDB ref exists)
    # Exclude folder pockets
    af_pdbs = glob.glob(os.path.join(locus_dir, '**', 'AF_*.pdb'), recursive=True)
    af_pdbs = [f for f in af_pdbs if 'pockets' not in f.split(os.sep)]
    af_pdbs = sorted(set(af_pdbs))
    
    if len(af_pdbs) > 1:
        print(f"  Warning: Found {len(af_pdbs)} AlphaFold models in {locus_dir}. Using first one.")
        print(f"  Using AlphaFold: {af_pdbs[0]}")
        return af_pdbs
    elif len(af_pdbs) == 1:
        #print(f"  Using AlphaFold model: {af_pdbs[0]}")
        return af_pdbs
    
    # 3) Third priority: ColabFold models (if no AlphaFold exists - FALLBACK ONLY)
    # Exclude folder pockets
    if colabfold:
        cb_pdbs = glob.glob(os.path.join(locus_dir, 'CB_*.pdb'))
        cb_pdbs = [f for f in cb_pdbs if 'pockets' not in f.split(os.sep) and 'colabfold_models' not in f.split(os.sep)]
        cb_pdbs = sorted(set(cb_pdbs))
        
        if len(cb_pdbs) > 1:
            print(f"  Warning: Found {len(cb_pdbs)} ColabFold models in {locus_dir}. Using first one.")
            print(f"  Using ColabFold: {cb_pdbs[0]}")
            return cb_pdbs
        elif len(cb_pdbs) == 1:
            print(f"  Using ColabFold model: {cb_pdbs[0]}")
            return cb_pdbs
    
    # 4) No reference structure found
    print(f"  Warning: No reference structure found in {locus_dir} (checked: *_ref.pdb, *_ref.cif, AF_*.pdb, CB_*.pdb)")
    return None


##  ------------------- ColabFold functions ------------------- ##


def find_colabfold_for_locus(locus_dir):
    """
    Find ColabFold model for parallel processing (when colabfold_run_all=True).
    This is separate from the default structure selection.
    
    :param locus_dir: Path to the locus_tag directory.
    :return: List with ColabFold model path, or None if not found.
    """
    cb_pdbs = glob.glob(os.path.join(locus_dir, 'CB_*.pdb'))
    cb_pdbs = [f for f in cb_pdbs if 'pockets' not in f.split(os.sep) and 'colabfold_models' not in f.split(os.sep)]
    cb_pdbs = sorted(set(cb_pdbs))
    
    if len(cb_pdbs) >= 1:
        # Return first CB model for parallel track
        return [cb_pdbs[0]]
    
    return None

def locus_tag_to_fasta(locus_tag, gbk_path, output_fasta):
    """
    Extract the sequence for a given locus_tag from a GenBank file and save it to a FASTA file.
    :param locus_tag: Locus tag identifier.
    :param gbk_path: Path to the GenBank file.
    :param output_fasta: Path to the output FASTA file.
    """
    from Bio import SeqIO

    with open(gbk_path, 'r') as gbk_file:
        for record in SeqIO.parse(gbk_file, 'genbank'):
            for feature in record.features:
                if feature.type == 'CDS' and 'locus_tag' in feature.qualifiers:
                    if locus_tag in feature.qualifiers['locus_tag']:
                        sequence = feature.qualifiers.get('translation', [''])[0]
                        if sequence:
                            with open(output_fasta, 'w') as fasta_file:
                                fasta_file.write(f">{locus_tag}\n{sequence}\n")
                            print(f"Extracted sequence for {locus_tag} to {output_fasta}")
                            return
    
    # If we reach here, locus_tag was not found
    logging.error(f"Locus tag {locus_tag} not found in {gbk_path}")

def get_colabfold_plddt(colabfold_dir):
    """
    Extract average pLDDT score from ColabFold JSON output.
    
    :param colabfold_dir: Directory containing ColabFold results.
    :return: Average pLDDT score as float, or None if not found.
    """
    import json
    
    # Find the scores JSON file for rank_001
    scores_files = glob.glob(os.path.join(colabfold_dir, "*_scores_rank_001*.json"))
    
    if not scores_files:
        logging.warning(f"No pLDDT scores file found in {colabfold_dir}")
        return None
    
    scores_file = scores_files[0]
    
    try:
        with open(scores_file, 'r') as f:
            scores_data = json.load(f)
        
        # The JSON contains a 'plddt' key with a list of per-residue scores
        if 'plddt' in scores_data:
            plddt_values = scores_data['plddt']
            if plddt_values:
                avg_plddt = sum(plddt_values) / len(plddt_values)
                return round(avg_plddt, 2)
        
        logging.warning(f"No 'plddt' key found in {scores_file}")
        return None
        
    except Exception as e:
        logging.error(f"Error reading pLDDT scores from {scores_file}: {e}")
        return None

def update_summary_table_with_colabfold(locus_dir, locus_tag, uniprot_id, model_path, plddt_score):
    """
    Update or create the structure summary table to include ColabFold model.
    
    ColabFold is added when NO other structure is already marked as reference
    (no eligible PDB/AF).

    :param locus_dir: Directory of the locus_tag.
    :param locus_tag: Locus tag identifier.
    :param uniprot_id: UniProt ID associated with the locus_tag.
    :param model_path: Path to the ColabFold model PDB file.
    :param plddt_score: Average pLDDT score.
    """
    summary_table_path = os.path.join(locus_dir, f"{locus_tag}_structure_summary.tsv")

    # Check if there's already a reference structure marked in the table
    colabfold_is_reference = True  

    if os.path.exists(summary_table_path):
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        summary_df = pd.read_csv(
            summary_table_path,
            sep='\t',
            dtype={'structure_id': str, 'uniprot_id': str, 'chain': str},
            keep_default_na=False,
            na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null']
        )
        has_reference = (summary_df['is_reference'] == True).any()
        if has_reference:
            colabfold_is_reference = False  # Another structure is already reference
    
    # Create a new entry for the ColabFold model
    colabfold_entry = {
        "locus_tag": locus_tag,
        "uniprot_id": uniprot_id,
        "structure_type": "ColabFold",
        "structure_id": "CB_" + locus_tag,
        "method": "AlphaFold2",
        "resolution": None,
        "chain": "A",
        "residue_range": None,
        "coverage": 100.0,
        "sequence_length": None,
        "is_reference": colabfold_is_reference,
        "plddt": plddt_score
    }
    
    # Check if summary table exists
    if os.path.exists(summary_table_path):
        # Read existing table
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        summary_df = pd.read_csv(
            summary_table_path,
            sep='\t',
            dtype={'structure_id': str, 'uniprot_id': str, 'chain': str},
            keep_default_na=False,
            na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null']
        )
        
        # Check for existing ColabFold entry
        existing_cf = summary_df[
            (summary_df['structure_type'] == 'ColabFold')]

        if not existing_cf.empty:
            logging.info(f"ColabFold entry already exists in summary table for {locus_tag}, skipping update.")
            return

        # Add plddt column if it doesn't exist
        if 'plddt' not in summary_df.columns:
            summary_df['plddt'] = None
               
        # Append ColabFold entry
        summary_df = pd.concat([summary_df, pd.DataFrame([colabfold_entry])], ignore_index=True)
    else:
        # Create new table with just the ColabFold entry
        summary_df = pd.DataFrame([colabfold_entry])
    
    # Save updated table
    summary_df.to_csv(summary_table_path, sep='\t', index=False, quoting=csv.QUOTE_NONNUMERIC)
    logging.info(f"Updated summary table for {locus_tag} with ColabFold model (pLDDT: {plddt_score})")


def generate_colabfold_missing_single(locus_tag, output_path, organism_name, structures_dir, map_results, amber_option=False, gpu_option=False):
    """
    Generate ColabFold models for a SINGLE protein IF it lacks structures.
    
    Only runs ColabFold if no existing structures (PDB, AF, or ColabFold) are found.
    Skips processing if structures already exist.
    
    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param structures_dir: Directory where structures are stored.
    :param map_results: Dictionary mapping locus tags to UniProt IDs.
    :param amber_option: If True, generate Amber-relaxed models. Default is False (unrelaxed).
    :param gpu_option: If True, use GPU for Amber relaxation. Default is False (CPU relaxation).
    """

    if locus_tag in map_results:
        uniprot_id = map_results[locus_tag]
        if isinstance(uniprot_id, list):
            uniprot_id = uniprot_id[0]  # Get first UniProt ID
    else:
        uniprot_id = None  

    locus_dir = os.path.join(structures_dir, locus_tag)
    colab_dir = os.path.join(locus_dir, "colabfold_models")

    relaxed_file = os.path.join(locus_dir, f"CB_{locus_tag}_relaxed1.pdb")
    unrelaxed_file = os.path.join(locus_dir, f"CB_{locus_tag}_unrelaxed1.pdb")

    dest_file = relaxed_file if amber_option else unrelaxed_file

    if os.path.exists(locus_dir):
        
        if not files.file_check(dest_file):
            # Check if there are ANY downloaded structures (PDB or AlphaFold)
            # This prevents ColabFold from running when structures exist but chain extraction failed
            pdb_structures = (
                glob.glob(os.path.join(locus_dir, "**", "PDB_*.pdb"), recursive=True) +
                glob.glob(os.path.join(locus_dir, "**", "PDB_*.cif"), recursive=True)
            )
            af_structures = glob.glob(os.path.join(locus_dir, "**", "AF_*.pdb"), recursive=True)

            if pdb_structures or af_structures:
                logging.info(f"Structures already exist for {locus_tag} (PDB: {len(pdb_structures)}, AF: {len(af_structures)}). Skipping ColabFold.")
                return
            
            # Also check using find_structures_for_locus (checks for _ref.pdb)
            pdb_file = find_structures_for_locus(locus_dir, colabfold=False, colabfold_all_models=False)
            if not pdb_file:
                logging.info(f"No structures found for {locus_dir}")
                logging.info(f"Generating models with ColabFold for {locus_dir}")
                # Extract sequence to FASTA
                fasta_file = os.path.join(locus_dir, f"{locus_tag}.fasta")
                locus_tag_to_fasta(
                    locus_tag,
                    os.path.join(output_path, organism_name, "genome", f"{organism_name}.gbk"),
                    fasta_file
                )
                
                os.makedirs(colab_dir, exist_ok=True)

                #Check if colab .done.txt file already exists to skip re-running
                output_colab_file = os.path.join(colab_dir, f"{locus_tag}.done.txt")
                if not os.path.exists(output_colab_file):
                    programs.run_colabfold_batch(fasta_file, colab_dir, amber=amber_option, gpu_relax=gpu_option)
                else:
                    logging.info(f"ColabFold .done.txt file found for {locus_tag}, skipping re-run.")

    
                model_copied = False
                if amber_option:
                    #find resulting relaxed model pdb
                    glob_pattern = os.path.join(colab_dir, "*_relaxed_rank_001*.pdb")
                    relaxed_models = glob.glob(glob_pattern)
                    if len(relaxed_models) == 1:
                        logging.info(f"  ColabFold relaxed model generated for {locus_tag}: {relaxed_models[0]}")
                        #copy to main locus_dir
                        shutil.copy2(relaxed_models[0], dest_file)
                        model_copied = True
                    else:
                        logging.warning(f"  Warning: Expected 1 relaxed model, found {len(relaxed_models)} for {locus_tag}")
                else:
                    #find resulting unrelaxed model pdb
                    glob_pattern = os.path.join(colab_dir, "*_unrelaxed_rank_001*.pdb")
                    unrelaxed_models = glob.glob(glob_pattern)
                    if len(unrelaxed_models) == 1:
                        logging.info(f"  ColabFold unrelaxed model generated for {locus_tag}: {unrelaxed_models[0]}")
                        #copy to main locus_dir
                        shutil.copy2(unrelaxed_models[0], dest_file)
                        model_copied = True
                    else:
                        logging.warning(f"  Warning: Expected 1 unrelaxed model, found {len(unrelaxed_models)} for {locus_tag}")
                
                # Update summary table with ColabFold model
                if model_copied:
                    plddt_score = get_colabfold_plddt(colab_dir)
                    update_summary_table_with_colabfold(locus_dir, locus_tag, uniprot_id, dest_file, plddt_score)
                    logging.info(f"  Added ColabFold model to summary table for {locus_tag}")
        else:
            logging.info(f"ColabFold model already exists for {locus_tag}.")
            plddt_score = get_colabfold_plddt(colab_dir)
            update_summary_table_with_colabfold(locus_dir, locus_tag, uniprot_id, dest_file, plddt_score)
            print(f"  Updated summary table with existing ColabFold model for {locus_tag} (pLDDT: {plddt_score})")
    else:
        logging.error(f"The directory '{locus_dir}' was not found.")

def generate_colabfold_missing(output_path, organism_name, amber_option=False, gpu_option=False):
    """
    Generate ColabFold models for proteins MISSING structures.
    
    Scans all proteins in the genome and runs ColabFold only for those without
    existing structures (PDB, AlphaFold, or previous ColabFold models).
    
    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param amber_option: If True, generate Amber-relaxed models. Default is False (unrelaxed).
    :param gpu_option: If True, use GPU for Amber relaxation. Default is False (CPU relaxation).
    """

    structures_dir = os.path.join(output_path, organism_name, "structures")
    
    if not os.path.exists(structures_dir):
        logging.error(f"The directory '{structures_dir}' was not found.")
        return

    proteome_ids_file = os.path.join(structures_dir, 'uniprot_files', f'uniprot_{organism_name}_id_mapping.json')

    if files.file_check(proteome_ids_file):
        map_results = files.json_to_dict(proteome_ids_file)
    else:
        map_results = {}
        logging.warning(f"UniProt ID mapping file not found: {proteome_ids_file}")

    all_locus = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in tqdm(all_locus, desc='Locus tags'):
        try:
            generate_colabfold_missing_single(locus_tag, output_path, organism_name, structures_dir, map_results, amber_option, gpu_option)
        except Exception as e:
            logging.error(f"Error occurred while running ColabFold for {locus_tag}: {e}")

def generate_colabfold_all_single(locus_tag, output_path, organism_name, structures_dir, map_results, amber_option=False, gpu_option=False):
    """
    Generate ColabFold models for a SINGLE protein (ALL proteins mode).
    
    Runs ColabFold for every protein regardless of existing structures.
        
    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param structures_dir: Directory where structures are stored.
    :param map_results: Dictionary mapping locus tags to UniProt IDs.
    :param amber_option: If True, generate Amber-relaxed models. Default is False (unrelaxed).
    :param gpu_option: If True, use GPU for Amber relaxation. Default is False (CPU relaxation).
    """

    if locus_tag in map_results:
        uniprot_id = map_results[locus_tag]
        if isinstance(uniprot_id, list):
            uniprot_id = uniprot_id[0]  # Get first UniProt ID
    else:
        uniprot_id = None  

    locus_dir = os.path.join(structures_dir, locus_tag)
    colab_dir = os.path.join(locus_dir, "colabfold_models")

    relaxed_file = os.path.join(locus_dir, f"CB_{locus_tag}_relaxed1.pdb")
    unrelaxed_file = os.path.join(locus_dir, f"CB_{locus_tag}_unrelaxed1.pdb")

    dest_file = relaxed_file if amber_option else unrelaxed_file

    if os.path.exists(locus_dir):
        
        if not files.file_check(dest_file):
            logging.info(f"Generating models with ColabFold for {locus_dir}")
            # Extract sequence to FASTA
            fasta_file = os.path.join(locus_dir, f"{locus_tag}.fasta")
            locus_tag_to_fasta(
                locus_tag,
                os.path.join(output_path, organism_name, "genome", f"{organism_name}.gbk"),
                fasta_file
            )
            
            os.makedirs(colab_dir, exist_ok=True)

            # Check if colab .done.txt file already exists to skip re-running
            output_colab_file = os.path.join(colab_dir, f"{locus_tag}.done.txt")
            if not os.path.exists(output_colab_file):
                programs.run_colabfold_batch(fasta_file, colab_dir, amber=amber_option, gpu_relax=gpu_option)
            else:
                logging.info(f"ColabFold .done.txt file found for {locus_tag}, skipping re-run.")

            model_copied = False
            if amber_option:
                #find resulting relaxed model pdb
                glob_pattern = os.path.join(colab_dir, "*_relaxed_rank_001*.pdb")
                relaxed_models = glob.glob(glob_pattern)
                if len(relaxed_models) == 1:
                    logging.info(f"  ColabFold relaxed model generated for {locus_tag}: {relaxed_models[0]}")
                    #copy to main locus_dir
                    shutil.copy2(relaxed_models[0], dest_file)
                    model_copied = True
                else:
                    logging.warning(f"  Warning: Expected 1 relaxed model, found {len(relaxed_models)} for {locus_tag}")
            else:
                #find resulting unrelaxed model pdb
                glob_pattern = os.path.join(colab_dir, "*_unrelaxed_rank_001*.pdb")
                unrelaxed_models = glob.glob(glob_pattern)
                if len(unrelaxed_models) == 1:
                    logging.info(f"  ColabFold unrelaxed model generated for {locus_tag}: {unrelaxed_models[0]}")
                    #copy to main locus_dir
                    shutil.copy2(unrelaxed_models[0], dest_file)
                    model_copied = True
                else:
                    logging.warning(f"  Warning: Expected 1 unrelaxed model, found {len(unrelaxed_models)} for {locus_tag}")
            # Update summary table with ColabFold model
            if model_copied:
                plddt_score = get_colabfold_plddt(colab_dir)
                update_summary_table_with_colabfold(locus_dir, locus_tag, uniprot_id, dest_file, plddt_score)
                logging.info(f"  Added ColabFold model to summary table for {locus_tag}")
        else:
            plddt_score = get_colabfold_plddt(colab_dir)
            update_summary_table_with_colabfold(locus_dir, locus_tag, uniprot_id, dest_file, plddt_score)
            logging.info(f"ColabFold model already exists for {locus_tag}.")
            print(f"  Updated summary table with existing ColabFold model for {locus_tag} (pLDDT: {plddt_score})")
    else:
        logging.error(f"The directory '{locus_dir}' was not found.")

def generate_colabfold_all(output_path, organism_name, amber_option=False, gpu_option=False):
    """
    Generate ColabFold models for ALL proteins in the genome.
    
    Runs ColabFold for every protein, regardless of existing structures.
    Useful for complete proteome coverage, bulk updates, or benchmarking.
        
    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param amber_option: If True, generate Amber-relaxed models. Default is False (unrelaxed).
    :param gpu_option: If True, use GPU for Amber relaxation. Default is False (CPU relaxation).
    """
    structures_dir = os.path.join(output_path, organism_name, "structures")
    
    if not os.path.exists(structures_dir):
        logging.error(f"The directory '{structures_dir}' was not found.")
        return

    proteome_ids_file = os.path.join(structures_dir, 'uniprot_files', f'uniprot_{organism_name}_id_mapping.json')

    if files.file_check(proteome_ids_file):
        map_results = files.json_to_dict(proteome_ids_file)
    else:
        map_results = {}
        logging.warning(f"UniProt ID mapping file not found: {proteome_ids_file}")

    all_locus = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in tqdm(all_locus, desc='Locus tags'):
        try:
            generate_colabfold_all_single(locus_tag, output_path, organism_name, structures_dir, map_results, amber_option, gpu_option)
        except Exception as e:
            logging.error(f"Error occurred while running ColabFold for {locus_tag}: {e}")


##  ------------------- Pocket functions ------------------- ##

def select_structures_for_pockets(locus_dir, full_mode=False, resolution_cutoff=3.5, coverage_cutoff=40.0, colabfold=False, colabfold_all_models=False):
    """
    Select structures for pocket prediction based on the specified mode.
    
    Modes:
    - 'ref': Select only the reference structure.
    - 'all': Select all available structures.

    :param locus_dir: Path to the locus_tag directory.
    :param full_mode: Boolean, if True processes all structures in each locus directory.
    :param resolution_cutoff: Float, maximum resolution to consider for selecting structures.
    :param coverage_cutoff: Float, minimum coverage to consider for selecting structures.
    :param colabfold: Boolean, if True includes ColabFold models in the selection.
    :param colabfold_all_models: Boolean, if True includes all ColabFold models instead of just the top-ranked one.
    
    :return: Both lists: 1) paths to selected structures, 2) their IDs.
    """

    if resolution_cutoff == None:
        resolution_cutoff = 3.5
        print(f"  No resolution cutoff provided, using default: {resolution_cutoff} Å")
    if coverage_cutoff == None:
        coverage_cutoff = 40.0
        print(f"  No coverage cutoff provided, using default: {coverage_cutoff} %")

    selected_structures_path = []
    selected_structures_ids = []

    locus_tag = os.path.basename(locus_dir)
    
    summary_table_path = os.path.join(locus_dir, f"{locus_tag}_structure_summary.tsv")

    if not full_mode:
        ref_structure = find_structures_for_locus(locus_dir, colabfold=colabfold, colabfold_all_models=colabfold_all_models)
        if ref_structure:
            selected_structures_path.extend(ref_structure)
        else:
            print(f"  Warning: No reference structure found in {locus_dir}.")
    else:
        elegible_pdbs = False
        elegible_af = False
        if files.file_check(summary_table_path):
            # Keep "NA" as string (valid chain name) instead of treating it as NaN
            summary_df = pd.read_csv(summary_table_path, sep='\t', dtype={'structure_id': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])
            #DF of PDBS
            PDBs_summary_df = summary_df[summary_df['structure_type'] == 'PDB']
            AFs_summary_df = summary_df[summary_df['structure_type'] == 'AlphaFold']
            CFs_summary_df = summary_df[summary_df['structure_type'] == 'ColabFold']

            for _, row in PDBs_summary_df.iterrows():
                uniprot_id = row['uniprot_id']
                if not uniprot_id or not isinstance(uniprot_id, str) or pd.isna(uniprot_id) or uniprot_id.strip() == '':
                    print(f"  Warning: Missing UniProt ID for structure {row['structure_id']} in {locus_dir}, skipping.")
                    continue

                struct_type = row['structure_type']
                struct_id = row['structure_id']
                coverage = row.get('coverage', None)
                resolution = row.get('resolution', None)
                
                uniprot_dir = os.path.join(locus_dir, uniprot_id)
                
                if (coverage is not None and coverage >= coverage_cutoff) and (resolution is not None and resolution <= resolution_cutoff):
                    
                    # PDB files - look for chain extracted files
                    pdb_glob = os.path.join(uniprot_dir, f"PDB_{struct_id}_*.pdb")
                    pdb_files = glob.glob(pdb_glob)
                    # Cif files - look for chain extracted files
                    cif_glob = os.path.join(uniprot_dir, f"PDB_{struct_id}_*.cif")
                    cif_files = glob.glob(cif_glob)

                    if pdb_files:
                        pdb_file_path = pdb_files[0]
                        # Check file validity
                        try:
                            pdb_valid = files.file_check(pdb_file_path) and os.path.getsize(pdb_file_path) > 0
                        except OSError:
                            pdb_valid = False
                    else:
                        pdb_file_path = None
                        pdb_valid = False
                    
                    if cif_files:
                        cif_file_path = cif_files[0]
                        try:
                            cif_valid = files.file_check(cif_file_path) and os.path.getsize(cif_file_path) > 0
                        except OSError:
                            cif_valid = False
                    else:
                        cif_file_path = None
                        cif_valid = False                    

                    
                    if pdb_valid:
                        selected_structures_path.extend([pdb_file_path])
                        selected_structures_ids.extend([struct_id])
                        elegible_pdbs = True
                    elif cif_valid:
                        selected_structures_path.extend([cif_file_path])
                        selected_structures_ids.extend([struct_id])
                        elegible_pdbs = True
                    else:
                        print(f"  Warning: No valid PDB or CIF file for {struct_id} in {locus_dir}.")
            
            if not elegible_pdbs and not AFs_summary_df.empty:
                for _, row in AFs_summary_df.iterrows():
                    uniprot_id = row['uniprot_id']
                    if not uniprot_id or not isinstance(uniprot_id, str) or pd.isna(uniprot_id) or uniprot_id.strip() == '':
                        print(f"  Warning: Missing UniProt ID for AlphaFold structure in {locus_dir}, skipping.")
                        continue
                    uniprot_dir = os.path.join(locus_dir, uniprot_id)
                    af_file_path = os.path.join(uniprot_dir, f"AF_{uniprot_id}.pdb")
                                        
                    try:
                        af_valid = files.file_check(af_file_path) and os.path.getsize(af_file_path) > 0
                    except OSError:
                        af_valid = False
                    
                    if af_valid:
                        selected_structures_path.extend([af_file_path])
                        selected_structures_ids.extend([f"AF_{uniprot_id}"])
                        elegible_af = True
                    else:
                        print(f"  Warning: No valid AlphaFold file for {uniprot_id} in {locus_dir}.")
            if not elegible_pdbs and not elegible_af and not CFs_summary_df.empty:
                for _, row in CFs_summary_df.iterrows():
                    struct_id = row['structure_id']
                    # Look for CB_*.pdb in locus_dir
                    glob_pattern = os.path.join(locus_dir, f"{struct_id}*.pdb")
                    cf_files = glob.glob(glob_pattern)
                    if not cf_files:
                        print(f"  Warning: No ColabFold file found for {struct_id} in {locus_dir}.")
                        continue 
                    cf_file_path = cf_files[0]
                    try:
                        cf_valid = files.file_check(cf_file_path) and os.path.getsize(cf_file_path) > 0
                    except OSError:
                        cf_valid = False
                    
                    if cf_valid:
                        selected_structures_path.extend([cf_file_path])
                        selected_structures_ids.extend([struct_id])
                    else:
                        print(f"  Warning: No valid ColabFold file for {locus_dir}.")       
    return selected_structures_path, selected_structures_ids


##  ------------------- FPocket functions ------------------- ##

def FPocket_models(directory):
    """
    Run Fpocket for all .pdb in a directory.
    Results are saved inside each fpocket output directory as all_pockets.json.

    :param directory: Directory with the models.
    """

    if os.path.exists(directory):
        for protein in tqdm(os.listdir(directory), desc="Processing", unit="protein"):
            protein_path = os.path.join(directory, protein)
            for template in os.listdir(protein_path):
                template_path = os.path.join(protein_path, template)
                for model_file in os.listdir(template_path):
                    model_pdb_path = os.path.join(template_path, model_file)
                    if os.path.isfile(model_pdb_path) and model_file.endswith('.pdb'):
                        fpocket_outdir = os.path.splitext(model_pdb_path)[0] + "_fpocket"
                        if not os.path.exists(fpocket_outdir):
                            print(f'Run Fpocket for {model_pdb_path}')
                            programs.run_fpocket(template_path, model_pdb_path)
                            print(f'FPocket prediction for {model_file} in {fpocket_outdir}.')
                            pockets_dict = pockets_data_to_dict(fpocket_outdir)
                            pockets_filter(pockets_dict)
    else:
        logging.error(f"The directory '{directory}' not found.")

def fpocket_for_structure(pdb, output_path, pockets_dir, container_engine='docker'):
    """
    Run Fpocket for a single PDB structure.

    This function uses the `run_fpocket` function from the `programs` module.
    Results are generated by Fpocket in a directory named '<pdb_basename>_fpocketc'
    inside `output_path`, and then moved into `pockets_dir`.

    :param pdb: Path to the PDB file.
    :param output_path: Directory where Fpocket will write its output.
    :param pockets_dir: Directory where the final pockets results will be stored.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    """

    fpocket_outdir = os.path.basename(os.path.splitext(pdb)[0]) + "_fpocket"
    results_path = os.path.join(pockets_dir, fpocket_outdir)

    if not os.path.exists(results_path):
        print(f'Running Fpocket for {pdb}')
        programs.run_fpocket(output_path, pdb, container_engine=container_engine)

        # Move the fpocket results to the pockets directory
        source_path = os.path.join(output_path, fpocket_outdir)
        
        # Remove destination if it exists (handles race conditions)
        if os.path.exists(results_path):
            shutil.rmtree(results_path)
        
        shutil.move(source_path, pockets_dir)

        print(f'FPocket prediction for {pdb} completed.')
    else:
        print(f'Fpocket results for {pdb} already present.')



def pockets_finder_for_locus(locus_dir, container_engine='docker', full_mode=False, colabfold=False, colabfold_all_models=False, resolution_cutoff=3.5, coverage_cutoff=40.0):
    """
    Run Fpocket for the selected structures in a locus_tag directory.

    This function handles TWO tracks:
    1) DEFAULT TRACK: Reference structure (PDB/AF priority, CB as fallback)
    2) PARALLEL COLABFOLD TRACK: CB model (only when colabfold_all_models=True)

    :param locus_dir: Path to the locus_tag directory.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param full_mode: If True, process all PDB files in the locus directory.
    :param colabfold: If True, consider ColabFold as fallback in default track.
    :param colabfold_all_models: If True, run parallel CB track for ALL proteins.
    :param resolution_cutoff: Float, maximum resolution to consider for selecting structures.
    :param coverage_cutoff: Float, minimum coverage to consider for selecting structures.
    """

    if os.path.exists(locus_dir):

        pockets_dir = os.path.join(locus_dir, 'pockets')
        os.makedirs(pockets_dir, exist_ok=True)

        # TRACK 1: DEFAULT - Select reference structure (PDB/AF priority, CB fallback)
        if not full_mode:
            pdb_files = find_structures_for_locus(locus_dir, colabfold=colabfold, colabfold_all_models=False)
            if pdb_files:
                for pdb_file in pdb_files:
                    print(f"Running Fpocket on default structure: {pdb_file}")
                    pdb_parent_dir = os.path.dirname(pdb_file)
                    fpocket_for_structure(pdb_file, pdb_parent_dir, pockets_dir, container_engine=container_engine)
            else:
                print(f"No default structures to process in {locus_dir}")
            
            # TRACK 2: PARALLEL COLABFOLD (only when ColabFold is installed AND colabfold_all_models=True)
            if colabfold and colabfold_all_models:
                cb_files = find_colabfold_for_locus(locus_dir)
                if cb_files:
                    for cb_file in cb_files:
                        print(f"Running Fpocket on ColabFold model: {cb_file}")
                        cb_parent_dir = os.path.dirname(cb_file)
                        fpocket_for_structure(cb_file, cb_parent_dir, pockets_dir, container_engine=container_engine)
        else:
            # FULL MODE: Process ALL PDB structures
            selected_structures_path = select_structures_for_pockets(locus_dir, full_mode=full_mode, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff, colabfold=colabfold, colabfold_all_models=False)[0]
            if not selected_structures_path:
                print(f"No structures to process in {locus_dir}")
            else:
                print(f"Running Fpocket on {len(selected_structures_path)} structures in {locus_dir}")

                with ProcessPoolExecutor() as executor:
                    futures = []
                    for pdb_file in selected_structures_path:
                        pdb_parent_dir = os.path.dirname(pdb_file)
                        futures.append(
                            executor.submit(
                                fpocket_for_structure,
                                pdb_file,
                                pdb_parent_dir,
                                pockets_dir,
                                container_engine
                            )
                        )

                    for future in tqdm(as_completed(futures), total=len(futures), desc="Fpocket progress"):
                        try:
                            future.result()
                        except Exception as e:
                            logging.error(f"Error during Fpocket execution: {e}")
            
            # TRACK 2: PARALLEL COLABFOLD (only when ColabFold is installed AND colabfold_all_models=True)
            if colabfold and colabfold_all_models:
                cb_files = find_colabfold_for_locus(locus_dir)
                if cb_files:
                    for cb_file in cb_files:
                        print(f"Running Fpocket on ColabFold model: {cb_file}")
                        cb_parent_dir = os.path.dirname(cb_file)
                        fpocket_for_structure(cb_file, cb_parent_dir, pockets_dir, container_engine=container_engine)
    else:
        logging.error(f"The directory '{locus_dir}' was not found.")


def pockets_finder_for_all_loci(output_path, organism_name, container_engine='docker', full_mode=False, colabfold=False, colabfold_all_models=False, resolution_cutoff=3.5, coverage_cutoff=40.0):
    """
    Run Fpocket for all locus_tag directories under the 'structures' folder.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param full_mode: If True, process all PDB files in each locus directory instead of just the reference or AlphaFold models.
    :param colabfold: If True, include ColabFold models in the processing.
    :param resolution_cutoff: Float, maximum resolution to consider for selecting structures.
    :param coverage_cutoff: Float, minimum coverage to consider for selecting structures.
    """

    structures_dir = os.path.join(output_path, organism_name, "structures")
    
    if not os.path.exists(structures_dir):
        logging.error(f"The directory '{structures_dir}' was not found.")
        return

    all_locus = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in tqdm(all_locus, desc='Locus tags'):
        locus_dir = os.path.join(structures_dir, locus_tag)
        if os.path.exists(locus_dir):
            pockets_finder_for_locus(locus_dir, container_engine=container_engine, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff)
        else:
            print(f"Locus directory '{locus_dir}' does not exist, skipping.")

def pockets_parse_output(content):
    """
    Parse the output of Fpocket.
    Returns a dictionary with the pockets data.

    :param content: Content of the fpocket output file.

    :return: Dictionary with the data
    """

    data = {}
    current_pocket = None

    pocket_re = re.compile(r"^Pocket (\d+) :")
    key_value_re = re.compile(r"\t(.+?) :\s+(.+)")

    for line in content.split('\n'):
        pocket_match = pocket_re.match(line)
        key_value_match = key_value_re.match(line)

        if pocket_match:
            current_pocket = f"Pocket {pocket_match.group(1)}"
            data[current_pocket] = {}
        elif key_value_match and current_pocket:
            key = key_value_match.group(1).strip()
            value = key_value_match.group(2).strip()
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass
            data[current_pocket][key] = value

    return data

def pockets_data_to_dict(directory):
    if os.path.exists(directory):
        pockets_file = os.path.join(directory, 'all_pockets.json')

        if not files.file_check(pockets_file):
            print('Parsing pockets results.')
            pockets_dict = {}
            
            for root, dirs, list_files in os.walk(directory):
                for file in list_files:
                    if file.endswith('_info.txt'):
                        file_path = os.path.join(root, file)
                        
                        # Extract structure ID from folder name
                        # E.g., "PDB_1ABC_A_ref_fpocket" -> "1ABC"
                        # or "AF_P12345_fpocket" -> "P12345"
                        folder_name = os.path.basename(root)
                        if folder_name.endswith('_fpocket'):
                            folder_name = folder_name[:-8]  # Remove '_fpocket'
                        
                        # Parse structure ID
                        parts = folder_name.split('_')
                        if parts[0] == 'PDB' and len(parts) >= 2:
                            protein_ID = parts[1]  # Get PDB code (e.g., "1ABC")
                        elif parts[0] == 'AF' and len(parts) >= 2:
                            protein_ID = '_'.join(parts[1:])  # Get full UniProt ID
                        elif parts[0] == 'CB' and len(parts) >= 2:
                            protein_ID = folder_name.rsplit("_", 1)[0]  # Get full ColabFold ID
                        else:
                            protein_ID = folder_name
                        
                        with open(file_path, 'r') as f:
                            content = f.read()
                            if content:
                                pockets_dict[protein_ID] = pockets_parse_output(content)
                            else:
                                pockets_dict[protein_ID] = 'No_pockets'

            files.dict_to_json(directory, 'all_pockets.json', pockets_dict)
            print(f'All pockets data saved to {pockets_file}.')
        else:
            pockets_dict = files.json_to_dict(pockets_file)
            print(f'All pockets data in {pockets_file}.')
        
        return pockets_dict
    else:
        print(f'{directory} not found.')
        return {}

def pockets_filter(pockets_dict):
    """
    Filter the pockets data to keep only the one with the highest Druggability Score.
    Returns a dictionary with the filtered data.

    :param pockets_dict: Dictionary with the pockets data.

    :return: Dictionary with the best pockets data. 
    """

    DS_dict = {}
    for prots, pockets in pockets_dict.items():
        if pockets_dict[prots] == 'No_pockets':
            DS_dict[prots] = 'No_pockets'
        else:
            n = 0
            max_pocket = None
            for pocket, props in pockets.items():
                for prop, value in props.items():
                    if prop == 'Druggability Score':
                        if value > n:
                            n = value
                            max_pocket = pocket

            DS_dict[prots] = {}
            DS_dict[prots]['maxDS'] = n
            DS_dict[prots]['pocket'] = max_pocket

    return DS_dict

##  ------------------- P2Rank functions ------------------- ##
def p2rank_for_structure(pdb, output_path, p2rank_dir, cpus, alphafold=False, container_engine='docker'):
    """
    Run P2Rank for a single PDB structure.

    This function uses the `run_p2rank` function from the `programs` module.
    Results are generated by P2Rank in a directory inside `output_path`, 
    and then moved into `p2rank_dir`.

    :param pdb: Path to the PDB file.
    :param output_path: Directory where P2Rank will write its output.
    :param p2rank_dir: Directory where the final P2Rank results will be stored.
    :param cpus: Number of CPUs/threads to use.
    :param alphafold: Boolean, if True adds '-c alphafold' to the command.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    """
    pdb_basename = os.path.basename(os.path.splitext(pdb)[0])
    
    output_folder = pdb_basename + "_p2rank"
    
    p2rank_output_dir_tmp = os.path.join(output_path, output_folder)
    p2rank_output_dir_final = os.path.join(p2rank_dir, output_folder)

    if os.path.exists(p2rank_output_dir_tmp):
        shutil.rmtree(p2rank_output_dir_tmp)

    if not os.path.exists(p2rank_output_dir_final) or not os.listdir(p2rank_output_dir_final):       

        try:
    
            print(f'Running P2Rank for {pdb}')
            # Run the p2rank Docker command
            programs.run_p2rank(output_path, pdb, cpus, alphafold=alphafold, container_engine=container_engine)

            # Move the output directory to the final destination
            shutil.move(p2rank_output_dir_tmp, p2rank_dir)
            print(f'P2Rank prediction for {pdb} completed.')
        except Exception as e:
            logging.exception(f'Error running P2Rank for {pdb}: {e}')
    else:
        print(f'P2Rank results directory for {pdb} already present.')


def p2rank_finder_for_locus(locus_dir, cpus, container_engine='docker', full_mode=False, colabfold=False, colabfold_all_models=False, resolution_cutoff=3.5, coverage_cutoff=40.0):
    """
    Run P2Rank for the selected structures in a locus_tag directory.

    This function handles TWO tracks:
    1) DEFAULT TRACK: Reference structure (PDB/AF priority, CB as fallback)
    2) PARALLEL COLABFOLD TRACK: CB model (only when colabfold_all_models=True)

    :param locus_dir: Path to the locus_tag directory.
    :param cpus: Number of CPUs/threads to use.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param full_mode: Boolean, if True processes all structures in the locus directory.
    :param colabfold: Boolean indicating whether to consider CB as fallback.
    :param colabfold_all_models: Boolean indicating whether to run parallel CB track.
    :param resolution_cutoff: Float, maximum resolution to consider for selecting structures.
    """

    if os.path.exists(locus_dir):

        p2rank_dir = os.path.join(locus_dir, 'pockets')
        os.makedirs(p2rank_dir, exist_ok=True)

        # TRACK 1: DEFAULT - Select reference structure (PDB/AF priority, CB fallback)
        if not full_mode:
            pdb_files = find_structures_for_locus(locus_dir, colabfold=colabfold, colabfold_all_models=False)
            if pdb_files:
                for pdb_file in pdb_files:
                    # Determine if it's an AlphaFold or ColabFold structure (both need alphafold flag)
                    pdb_basename = os.path.basename(pdb_file)
                    is_alphafold = pdb_basename.startswith('AF_') or pdb_basename.startswith('CB_')
                    
                    print(f"Running P2Rank on default structure: {pdb_file} (AlphaFold={is_alphafold})")
                    
                    pdb_parent_dir = os.path.dirname(pdb_file)
                    p2rank_for_structure(pdb_file, pdb_parent_dir, p2rank_dir, cpus, alphafold=is_alphafold, container_engine=container_engine)
            else:
                print(f"No default structures to process in {locus_dir}")
            
            # TRACK 2: PARALLEL COLABFOLD (only when ColabFold is installed AND colabfold_all_models=True)
            if colabfold and colabfold_all_models:
                cb_files = find_colabfold_for_locus(locus_dir)
                if cb_files:
                    for cb_file in cb_files:
                        print(f"Running P2Rank on ColabFold model: {cb_file}")
                        cb_parent_dir = os.path.dirname(cb_file)
                        p2rank_for_structure(cb_file, cb_parent_dir, p2rank_dir, cpus, alphafold=True, container_engine=container_engine)
        else:
            # FULL MODE: Process ALL PDB structures
            selected_structures_path = select_structures_for_pockets(locus_dir, full_mode=full_mode, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff, colabfold=colabfold, colabfold_all_models=False)[0]
            if not selected_structures_path:
                print(f"No structures to process in {locus_dir}")
            else:
                print(f"Running P2Rank on {len(selected_structures_path)} structures in {locus_dir}")

                for pdb_file in tqdm(selected_structures_path, desc="P2Rank progress"):
                    pdb_basename = os.path.basename(pdb_file)
                    is_alphafold = pdb_basename.startswith('AF_') or pdb_basename.startswith('CB_')
                    
                    pdb_parent_dir = os.path.dirname(pdb_file)
                    p2rank_for_structure(pdb_file, pdb_parent_dir, p2rank_dir, cpus, alphafold=is_alphafold, container_engine=container_engine)
            
            # TRACK 2: PARALLEL COLABFOLD (only when ColabFold is installed AND colabfold_all_models=True)
            if colabfold and colabfold_all_models:
                cb_files = find_colabfold_for_locus(locus_dir)
                if cb_files:
                    for cb_file in cb_files:
                        print(f"Running P2Rank on ColabFold model: {cb_file}")
                        cb_parent_dir = os.path.dirname(cb_file)
                        p2rank_for_structure(cb_file, cb_parent_dir, p2rank_dir, cpus, alphafold=True, container_engine=container_engine)                                        
    else:
        logging.error(f"The directory '{locus_dir}' was not found.")

def p2rank_finder_for_all_loci(output_path, organism_name, cpus, container_engine='docker', full_mode=False, colabfold=False, colabfold_all_models=False, resolution_cutoff=3.5, coverage_cutoff=40.0):
    """
    Run P2Rank for all locus_tag directories under the 'structures' folder.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param cpus: Number of CPUs/threads to use.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param full_mode: Boolean, if True processes all structures in each locus directory.
    :param colabfold: Boolean indicating whether to run ColabFold or not (default: False).
    :param resolution_cutoff: Float, maximum resolution to consider for selecting structures.
    :param coverage_cutoff: Float, minimum coverage to consider for selecting structures.
    """

    structures_dir = os.path.join(output_path, organism_name, "structures")
    
    if not os.path.exists(structures_dir):
        logging.error(f"The directory '{structures_dir}' was not found.")
        return

    all_locus = metadata.ref_gbk_locus(output_path, organism_name)

    for locus_tag in tqdm(all_locus, desc='Locus tags'):
        locus_dir = os.path.join(structures_dir, locus_tag)
        if os.path.exists(locus_dir):
            p2rank_finder_for_locus(locus_dir, cpus, container_engine=container_engine, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff)
        else:
            print(f"Locus directory '{locus_dir}' does not exist, skipping.")


def p2rank_parse_predictions(csv_file):
    """
    Parse P2Rank predictions CSV file to extract pocket information.
    
    The CSV file contains columns including 'name' (pocket number) and 'probability'
    (probability of being a ligand-binding site).
    
    :param csv_file: Path to the *_predictions.csv file from P2Rank.
    :return: Dictionary with pocket information, or 'No_pockets' if no data found.
    """
    if not os.path.exists(csv_file):
        return 'No_pockets'
    
    try:
        # Use skipinitialspace=True to strip leading whitespace after commas
        df = pd.read_csv(csv_file, sep=',', skipinitialspace=True)
        
        # Strip whitespace from column names
        df.columns = df.columns.str.strip()
        
        # Check if required columns exist
        if 'name' not in df.columns or 'probability' not in df.columns:
            print(f"Warning: Required columns 'name' and/or 'probability' not found in {csv_file}")
            return 'No_pockets'
        
        # Check if there are any pockets
        if len(df) == 0:
            return 'No_pockets'
        
        # Create dictionary with pocket data
        pockets_dict = {}
        for _, row in df.iterrows():
            pocket_name = f"Pocket {row['name']}"
            pockets_dict[pocket_name] = {
                'probability': float(row['probability'])
            }
        
        return pockets_dict
        
    except Exception as e:
        logging.exception(f"Error parsing P2Rank predictions file {csv_file}: {e}")
        return 'No_pockets'


def p2rank_data_to_dict(directory):
    """
    Parse P2Rank results from a directory to extract pocket predictions.
    
    This function can handle TWO modes:
    1. Single p2rank folder (e.g., "PDB_1ABC_p2rank") - returns results for that structure
    2. Parent directory containing multiple *_p2rank folders - returns aggregated results
    
    :param directory: Path to a p2rank folder OR parent directory containing p2rank folders.
    :return: Dictionary with P2Rank pocket data for structure(s).
    """
    if not os.path.exists(directory):
        print(f'Error: {directory} not found.')
        return {}
    
    # MODE 1: Check if this directory itself IS a p2rank folder
    if directory.endswith('_p2rank'):
        # Single p2rank folder mode - parse directly
        p2rank_file = os.path.join(directory, 'p2rank_pockets.json')
        
        if not files.file_check(p2rank_file):
            print(f'Parsing P2Rank results from {os.path.basename(directory)}.')
            p2rank_dict = {}
            
            # Extract structure ID from folder name
            folder_name = os.path.basename(directory).replace('_p2rank', '')
            parts = folder_name.split('_')
            
            if parts[0] == 'PDB' and len(parts) >= 2:
                protein_ID = parts[1]  # Get PDB code
            elif parts[0] == 'AF' and len(parts) >= 2:
                protein_ID = '_'.join(parts[1:])  # Get UniProt ID
            elif parts[0] == 'CB' and len(parts) >= 2:
                protein_ID = folder_name.rsplit("_", 1)[0]  # Get ColabFold ID
            else:
                protein_ID = folder_name
            
            # Find the predictions CSV file
            predictions_file = None
            for file in os.listdir(directory):
                if file.endswith('_predictions.csv'):
                    predictions_file = os.path.join(directory, file)
                    break
            
            if predictions_file:
                p2rank_dict[protein_ID] = p2rank_parse_predictions(predictions_file)
            else:
                print(f"Warning: No predictions CSV file found in {directory}")
                p2rank_dict[protein_ID] = 'No_pockets'
            
            files.dict_to_json(directory, 'p2rank_pockets.json', p2rank_dict)
        else:
            p2rank_dict = files.json_to_dict(p2rank_file)
        
        return p2rank_dict
    
    # MODE 2: Parent directory mode - scan for all *_p2rank subdirectories
    p2rank_file = os.path.join(directory, 'all_p2rank_pockets.json')
    
    if not files.file_check(p2rank_file):
        print('Parsing P2Rank results.')
        p2rank_dict = {}
        
        # Find all P2Rank output directories (ending with _p2rank)
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            
            if os.path.isdir(item_path) and item.endswith('_p2rank'):
                # Extract structure ID from folder name
                folder_name = item.replace('_p2rank', '')
                parts = folder_name.split('_')
                
                if parts[0] == 'PDB' and len(parts) >= 2:
                    protein_ID = parts[1]  # Get PDB code
                elif parts[0] == 'AF' and len(parts) >= 2:
                    protein_ID = '_'.join(parts[1:])  # Get UniProt ID
                elif parts[0] == 'CB' and len(parts) >= 2:
                    protein_ID = folder_name.rsplit("_", 1)[0]  # Get ColabFold ID
                else:
                    protein_ID = folder_name
                
                # Find the predictions CSV file
                predictions_file = None
                for file in os.listdir(item_path):
                    if file.endswith('_predictions.csv'):
                        predictions_file = os.path.join(item_path, file)
                        break
                
                if predictions_file:
                    p2rank_dict[protein_ID] = p2rank_parse_predictions(predictions_file)
                else:
                    print(f"Warning: No predictions CSV file found in {item_path}")
                    p2rank_dict[protein_ID] = 'No_pockets'
        
        files.dict_to_json(directory, 'all_p2rank_pockets.json', p2rank_dict)
        print(f'All P2Rank pocket data saved to {p2rank_file}.')
    else:
        p2rank_dict = files.json_to_dict(p2rank_file)
        print(f'All P2Rank pocket data loaded from {p2rank_file}.')
    
    return p2rank_dict


def p2rank_filter(p2rank_dict):
    """
    Filter P2Rank pockets to keep only the one with the highest probability.
    
    This function returns a dictionary
    with the best pocket (highest probability) for each structure.
    
    :param p2rank_dict: Dictionary with P2Rank pocket data.
    :return: Dictionary with the best pocket data (highest probability).
    """
    best_pockets_dict = {}
    
    for protein_id, pockets in p2rank_dict.items():
        if pockets == 'No_pockets':
            best_pockets_dict[protein_id] = 'No_pockets'
        else:
            max_prob = 0
            max_pocket = None
            
            for pocket_name, props in pockets.items():
                probability = props.get('probability', 0)
                if probability > max_prob:
                    max_prob = probability
                    max_pocket = pocket_name
            
            best_pockets_dict[protein_id] = {
                'max_probability': max_prob,
                'pocket': max_pocket
            }
    
    return best_pockets_dict

def select_best_pocket_dict(pocket_dict, mode='fpocket'):
    """
    Select the best pocket from a given pocket dictionary based on maximum score.
    From a list of dicts like this {"7PTF": {"max_probability": 0.574, "pocket": "Pocket pocket1 "}, ...} 
    it selects the one with the highest 'max_probability' or 'maxDS' score.
    :param pocket_dict: Dictionary containing pocket data with scores.
    :return: Dictionary with the best pocket information.
    """
    max_score = -float('inf')
    best_pocket = None
    no_pockets_fallback = None

    for pocket in pocket_dict:
        for struct_name, props in pocket.items():
            if not isinstance(props, dict):
                no_pockets_fallback = {struct_name: 'No_pockets'}
                continue  # Skip if props is not a dictionary
            if mode == 'fpocket':
                score = props.get('maxDS', -float('inf'))
            elif mode == 'p2rank':
                score = props.get('max_probability', -float('inf'))
            else:
                raise ValueError(f"Unknown mode '{mode}' for selecting best pocket.")

            if score > max_score:
                max_score = score
                best_pocket = pocket
    
    if best_pocket is None:
        if no_pockets_fallback is not None:
            return no_pockets_fallback
        else:
            return {}

    return best_pocket 

def merge_structure_data (output_path, organism_name, full_mode=False, colabfold=False, colabfold_all_models=False):
    """
    Merge all the structure data in a single dictionary.
    Saves the dictionary in a .json file named using the organism name followed by '_structure_data.json' in the 'structures' directory.
    Returns a dictionary with the merged data.

    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of the organism.
    :param full_mode: If True, processes all pockets data instead of just the best ones. Gives the maximum value.
    :param colabfold: Boolean, if True includes ColabFold models in the selection.
    :param colabfold_all_models: Boolean, if True includes all ColabFold models

    :return: Dictionary with the merged data.
    """

    structure_dir = os.path.join(output_path, organism_name, 'structures')
    merged_file = os.path.join(structure_dir, f'{organism_name}_structure_data.json')

    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)

    if not files.file_check(merged_file):

        print('Merging all structure data.')

        merged_dict = {}

        for locus_tag in tqdm(all_locus_tags, desc='Locus tags'):

            locus_dir = os.path.join(structure_dir, locus_tag)
            
            # Skip if locus directory doesn't exist
            if not os.path.isdir(locus_dir):
                continue

            # Initialize entry for this locus_tag
            if locus_tag not in merged_dict:
                merged_dict[locus_tag] = {}

            # ========== FPocket Data ==========
            pockets_dir = os.path.join(locus_dir, 'pockets')
            
            if os.path.isdir(pockets_dir):
                # Get all fpocket folders
                all_fpocket_folders = [d for d in os.listdir(pockets_dir) if d.endswith('_fpocket') and os.path.isdir(os.path.join(pockets_dir, d))]
                
                # Separate DEFAULT track and COLABFOLD track results
                default_fpocket_folders = [f for f in all_fpocket_folders if not f.startswith('CB_')]
                colabfold_fpocket_folders = [f for f in all_fpocket_folders if f.startswith('CB_')]
                
                # Process DEFAULT track fpocket results
                if default_fpocket_folders:
                    best_pockets_file = os.path.join(pockets_dir, f'best_DS_fpocket_{locus_tag}.json')
                    
                    if not files.file_check(best_pockets_file):
                        if not full_mode and len(default_fpocket_folders) == 1:
                            # Single default structure
                            fpocket_folder_path = os.path.join(pockets_dir, default_fpocket_folders[0])
                            pockets_dict = pockets_data_to_dict(fpocket_folder_path)
                            best_pockets_dict = pockets_filter(pockets_dict)
                            files.dict_to_json(pockets_dir, f'best_DS_fpocket_{locus_tag}.json', best_pockets_dict)
                            merged_dict[locus_tag]['fpocket_best_pockets'] = best_pockets_dict
                            
                        elif full_mode:
                            # Multiple PDB structures - find best across all
                            fpocket_structures_best_pockets = []
                            for fpocket_folder_name in default_fpocket_folders:
                                fpocket_folder_path = os.path.join(pockets_dir, fpocket_folder_name)
                                pockets_dict = pockets_data_to_dict(fpocket_folder_path)
                                best_pockets_dict = pockets_filter(pockets_dict)
                                fpocket_structures_best_pockets.append(best_pockets_dict)
                            
                            if fpocket_structures_best_pockets:
                                files.dict_to_json(pockets_dir, f'all_best_DS_fpocket_{locus_tag}.json', fpocket_structures_best_pockets)
                                best_pocket = select_best_pocket_dict(fpocket_structures_best_pockets, mode='fpocket')
                                files.dict_to_json(pockets_dir, f'best_DS_fpocket_{locus_tag}.json', best_pocket)
                                merged_dict[locus_tag]['fpocket_best_pockets'] = best_pocket
                    else:
                        best_pockets_dict = files.json_to_dict(best_pockets_file)
                        merged_dict[locus_tag]['fpocket_best_pockets'] = best_pockets_dict
                
                # Process COLABFOLD track fpocket results (only when ColabFold installed AND enabled)
                if colabfold and colabfold_fpocket_folders:
                    colabfold_pockets_file = os.path.join(pockets_dir, f'best_DS_fpocket_colabfold_{locus_tag}.json')
                    
                    if not files.file_check(colabfold_pockets_file):
                        # Process first ColabFold result
                        cf_folder_path = os.path.join(pockets_dir, colabfold_fpocket_folders[0])
                        cf_pockets_dict = pockets_data_to_dict(cf_folder_path)
                        cf_best_pockets_dict = pockets_filter(cf_pockets_dict)
                        files.dict_to_json(pockets_dir, f'best_DS_fpocket_colabfold_{locus_tag}.json', cf_best_pockets_dict)
                        merged_dict[locus_tag]['fpocket_colabfold_pockets'] = cf_best_pockets_dict
                    else:
                        cf_best_pockets_dict = files.json_to_dict(colabfold_pockets_file)
                        merged_dict[locus_tag]['fpocket_colabfold_pockets'] = cf_best_pockets_dict

            # ========== P2Rank Data ==========
            p2rank_dir = os.path.join(locus_dir, 'pockets')
            
            if os.path.isdir(p2rank_dir):
                # Get all p2rank folders
                all_p2rank_folders = [d for d in os.listdir(p2rank_dir) if d.endswith('_p2rank') and os.path.isdir(os.path.join(p2rank_dir, d))]
                
                # Separate DEFAULT track and COLABFOLD track results
                default_p2rank_folders = [f for f in all_p2rank_folders if not f.startswith('CB_')]
                colabfold_p2rank_folders = [f for f in all_p2rank_folders if f.startswith('CB_')]
                
                # Process DEFAULT track p2rank results
                if default_p2rank_folders:
                    best_p2rank_file = os.path.join(p2rank_dir, f'best_prob_p2rank_{locus_tag}.json')
                    
                    if not files.file_check(best_p2rank_file):
                        if not full_mode and len(default_p2rank_folders) == 1:
                            # Single default structure - pass specific folder path
                            p2rank_folder_path = os.path.join(p2rank_dir, default_p2rank_folders[0])
                            p2rank_dict = p2rank_data_to_dict(p2rank_folder_path)
                            best_p2rank_dict = p2rank_filter(p2rank_dict)
                            files.dict_to_json(p2rank_dir, f'best_prob_p2rank_{locus_tag}.json', best_p2rank_dict)
                            merged_dict[locus_tag]['p2rank_best_pockets'] = best_p2rank_dict
                            
                        elif full_mode:
                            # Multiple PDB structures - find best across all (SAME AS FPOCKET)
                            p2rank_structures_best_pockets = []
                            for p2rank_folder_name in default_p2rank_folders:
                                # Pass specific p2rank folder path (matching fpocket logic)
                                p2rank_folder_path = os.path.join(p2rank_dir, p2rank_folder_name)
                                p2rank_dict = p2rank_data_to_dict(p2rank_folder_path)
                                best_p2rank_dict = p2rank_filter(p2rank_dict)
                                p2rank_structures_best_pockets.append(best_p2rank_dict)
                            
                            if p2rank_structures_best_pockets:
                                files.dict_to_json(p2rank_dir, f'all_best_prob_p2rank_{locus_tag}.json', p2rank_structures_best_pockets)
                                best_pocket = select_best_pocket_dict(p2rank_structures_best_pockets, mode='p2rank')
                                files.dict_to_json(p2rank_dir, f'best_prob_p2rank_{locus_tag}.json', best_pocket)
                                merged_dict[locus_tag]['p2rank_best_pockets'] = best_pocket
                    else:
                        best_p2rank_dict = files.json_to_dict(best_p2rank_file)
                        merged_dict[locus_tag]['p2rank_best_pockets'] = best_p2rank_dict
                
                # Process COLABFOLD track p2rank results (only when ColabFold installed AND enabled)
                if colabfold and colabfold_p2rank_folders:
                    colabfold_p2rank_file = os.path.join(p2rank_dir, f'best_prob_p2rank_colabfold_{locus_tag}.json')
                    
                    if not files.file_check(colabfold_p2rank_file):
                        # Process ColabFold p2rank result - pass specific folder path
                        if colabfold_p2rank_folders:
                            colabfold_p2rank_folder_path = os.path.join(p2rank_dir, colabfold_p2rank_folders[0])
                            p2rank_dict = p2rank_data_to_dict(colabfold_p2rank_folder_path)
                            best_p2rank_dict = p2rank_filter(p2rank_dict)
                            files.dict_to_json(p2rank_dir, f'best_prob_p2rank_colabfold_{locus_tag}.json', best_p2rank_dict)
                            merged_dict[locus_tag]['p2rank_colabfold_pockets'] = best_p2rank_dict
                    else:
                        best_p2rank_dict = files.json_to_dict(colabfold_p2rank_file)
                        merged_dict[locus_tag]['p2rank_colabfold_pockets'] = best_p2rank_dict

        files.dict_to_json(structure_dir, f'{organism_name}_structure_data.json', merged_dict)
        return merged_dict
    
    else:
        merged_dict = files.json_to_dict(merged_file)
        print(f'Merged structure data in {merged_file}.')
        return merged_dict

def final_structure_table(output_path, organism_name, full_mode=False, colabfold=False, colabfold_all_models=False):
    """
    Create a final summary table with structure and pocket information for each locus_tag.
    The table columns are as follows:
    -Not full_mode: gene, uniprot, structure, druggability_score, fpocket_pocket, p2rank_probability, p2rank_pocket
    -Full_mode: gene, uniprot, structure, best_fpocket_structure, druggability_score, fpocket_pocket, 
    best_p2rank_structure, p2rank_probability, p2rank_pocket
    -If colabfold_all_models (added to either mode): colabfold_plddt, colabfold_druggability_score, 
    colabfold_fpocket_pocket, colabfold_p2rank_probability, colabfold_p2rank_pocket


    :param output_path: Directory of the oraganism output.
    :param organism_name: Name of organism.
    :param full_mode: Boolean indicating whether to use full pocket mode for processing.
    :param colabfold: Boolean indicating whether to include ColabFold models (default: False).
    :param colabfold_all_models: Boolean indicating whether to include all ColabFold models
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    merged_file = os.path.join(structure_dir, f'{organism_name}_structure_data.json')
    final_table_file = os.path.join(structure_dir, f'{organism_name}_final_structure_summary.tsv')

    proteome_map_file = os.path.join(structure_dir, 'uniprot_files', f'uniprot_{organism_name}_id_mapping.json')
    map_results = files.json_to_dict(proteome_map_file) if files.file_check(proteome_map_file) else {}

    def get_pocket_data(locus_tag, uniprot_id, structure_id, structure_type, data, colabfold_track=False):
        """
        Helper function to retrieve pocket data for a given locus_tag and structure.
        
        :param colabfold_track: If True, extract from ColabFold parallel track data
        """
        
        # Select data source based on track
        if colabfold_track:
            fpocket_data = data.get('fpocket_colabfold_pockets', {})
            p2rank_data = data.get('p2rank_colabfold_pockets', {})
        else:
            fpocket_data = data.get('fpocket_best_pockets', {})
            p2rank_data = data.get('p2rank_best_pockets', {})
        
        # ========== FPocket Data ==========
        druggability_score = None
        fpocket_pocket = None
        
        if fpocket_data and structure_id:
            # For AlphaFold structures, use UniProt ID as key
            # For PDB structures, use PDB code as key
            if structure_type == 'AlphaFold':
                pocket_key = uniprot_id
            elif structure_type == 'ColabFold':
                pocket_key = f'CB_{locus_tag}'
            else:
                pocket_key = structure_id
            
            pocket_info = fpocket_data.get(pocket_key)
            if pocket_info:
                if pocket_info != 'No_pockets':
                    druggability_score = pocket_info.get('maxDS')
                    fpocket_pocket = pocket_info.get('pocket')
                else:
                    fpocket_pocket = 'No_pockets'
        
        # ========== P2Rank Data ==========
        p2rank_probability = None
        p2rank_pocket = None
        
        if p2rank_data and structure_id:
            # For AlphaFold structures, use UniProt ID as key
            # For PDB structures, use PDB code as key
            if structure_type == 'AlphaFold':
                pocket_key = uniprot_id
            elif structure_type == 'ColabFold':
                pocket_key = f'CB_{locus_tag}'
            else:
                pocket_key = structure_id
            
            pocket_info = p2rank_data.get(pocket_key)
            if pocket_info:
                if pocket_info != 'No_pockets':
                    p2rank_probability = pocket_info.get('max_probability')
                    p2rank_pocket = pocket_info.get('pocket')
                else:
                    p2rank_pocket = 'No_pockets'
                    
        return druggability_score, fpocket_pocket, p2rank_probability, p2rank_pocket
    
    if not files.file_check(final_table_file):
        
        if not files.file_check(merged_file):
            merged_dict = merge_structure_data(output_path, organism_name)
        else:
            merged_dict = files.json_to_dict(merged_file)

        rows = []
        all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)

        for locus_tag in all_locus_tags:

            # Get uniprot id from proteome mapping
            if map_results:
                uniprot_id = map_results.get(locus_tag)
                if isinstance(uniprot_id, list):
                    uniprot_id = uniprot_id[0]
            else:
                uniprot_id = None

            # Get pocket data for the reference structure
            data = merged_dict.get(locus_tag, {})

            # Get UniProt ID and structure ID from REFERENCE structure only
            structure_summary_path = os.path.join(
                structure_dir, locus_tag, f"{locus_tag}_structure_summary.tsv"
            )
            
            # Initialize all variables before conditional blocks
            structure_id = None
            structure_ids = None
            structure_type = None
            druggability_score = None
            fpocket_pocket = None
            p2rank_probability = None
            p2rank_pocket = None
            colabfold_best_pocket = None
            colabfold_plddt = None
            fp_uniprot_id = None
            pr_uniprot_id = None
            CB_druggability_score = None
            CB_fpocket_pocket = None
            CB_p2rank_probability = None
            CB_p2rank_pocket = None
            best_fpocket_id = None
            best_p2rank_id = None
            
            if files.file_check(structure_summary_path):
                # Read structure_id as string to prevent scientific notation (e.g., 3E59 -> 3e+59)
                # Keep "NA" as string (valid chain name) instead of treating it as NaN
                struct_df = pd.read_csv(structure_summary_path, sep='\t', dtype={'structure_id': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])
              
                if not full_mode:
                
                    ref_rows = struct_df[struct_df['is_reference'] == True]
                    
                    if not ref_rows.empty:
                        if len(ref_rows) > 1:
                            print(f'  Warning: Multiple reference structures for {locus_tag}, using first.')
                        ref_row = ref_rows.iloc[0]
                        if ref_row['uniprot_id'] != uniprot_id:
                            print(f'  Warning: Different UniProt ID in reference structure ({ref_row["uniprot_id"]}) and mapping ({uniprot_id}) for {locus_tag}.')
                            uniprot_id = ref_row['uniprot_id']
                        structure_id = ref_row['structure_id']
                        structure_type = ref_row['structure_type']

                        use_colabfold_track = (structure_type == 'ColabFold' and colabfold)

                        druggability_score, fpocket_pocket, p2rank_probability, p2rank_pocket = get_pocket_data(locus_tag, uniprot_id, structure_id, structure_type, data, colabfold_track=use_colabfold_track)
                else:

                    # Select best structure for FPocket and P2Rank independently
                    fpocket_best = data.get('fpocket_best_pockets') or data.get('fpocket_colabfold_pockets') or {}
                    p2rank_best = data.get('p2rank_best_pockets') or data.get('p2rank_colabfold_pockets') or {}

                    best_fpocket_id = next(iter(fpocket_best.keys()), None)
                    best_p2rank_id = next(iter(p2rank_best.keys()), None)

                    all_structures_list = [s for s in struct_df['structure_id'].tolist() if s not in (None, 'NONE', 'nan', float('nan'), '')]
                    structure_ids = set(all_structures_list)

                    if not structure_ids:
                        structure_ids = None

                    # Resolve FPocket best structure row
                    if best_fpocket_id:
                        fp_row = struct_df[struct_df['structure_id'] == best_fpocket_id]
                        if not fp_row.empty:
                            fp_row = fp_row.iloc[0]
                            fp_uniprot_id = fp_row['uniprot_id']
                            fp_structure_id = fp_row['structure_id']
                            fp_structure_type = fp_row['structure_type']
                            fp_use_colabfold = (fp_structure_type == 'ColabFold' and colabfold)

                            druggability_score, fpocket_pocket, _, _ = get_pocket_data(
                                locus_tag, fp_uniprot_id, fp_structure_id, fp_structure_type, data, colabfold_track=fp_use_colabfold
                            )

                    # Resolve P2Rank best structure row
                    if best_p2rank_id:
                        pr_row = struct_df[struct_df['structure_id'] == best_p2rank_id]
                        if not pr_row.empty:
                            pr_row = pr_row.iloc[0]
                            pr_uniprot_id = pr_row['uniprot_id']
                            pr_structure_id = pr_row['structure_id']
                            pr_structure_type = pr_row['structure_type']
                            pr_use_colabfold = (pr_structure_type == 'ColabFold' and colabfold)

                            _, _, p2rank_probability, p2rank_pocket = get_pocket_data(
                                locus_tag, pr_uniprot_id, pr_structure_id, pr_structure_type, data, colabfold_track=pr_use_colabfold
                            )
                                        
                    candidates = [uniprot_id, fp_uniprot_id, pr_uniprot_id]
                    candidates = [x for x in candidates if x is not None and not pd.isna(x)]
                    uniprot_id = "|".join(sorted({str(x) for x in candidates if str(x).strip() != ""}))

                if colabfold_all_models:
                    colab_rows = struct_df[struct_df['structure_type'] == 'ColabFold']
                    if not colab_rows.empty:
                        # Get first ColabFold row
                        colab_row = colab_rows.iloc[0]
                        colabfold_plddt = colab_row.get('plddt', None)
                        cf_locus_tag = colab_row.get('locus_tag', locus_tag)
                        cf_structure_id = colab_row.get('structure_id', None)
                        cf_uniprot_id = colab_row.get('uniprot_id', None)
                        if cf_uniprot_id != uniprot_id:
                            print(f'  Warning: Different UniProt ID in ColabFold structure ({cf_uniprot_id}) and mapping ({uniprot_id}) for {locus_tag}.')
                            
                        # Extract ColabFold data from PARALLEL TRACK (colabfold_track=True)
                        CB_druggability_score, CB_fpocket_pocket, CB_p2rank_probability, CB_p2rank_pocket = get_pocket_data(
                            cf_locus_tag, cf_uniprot_id, cf_structure_id, 'ColabFold', data, colabfold_track=True
                        )

            row = {
                'gene': locus_tag,
                'uniprot': uniprot_id,
            }

            if full_mode:
                row.update({
                    'structure': structure_ids,
                    'best_fpocket_structure': best_fpocket_id,
                    'druggability_score': druggability_score,
                    'fpocket_pocket': fpocket_pocket,
                    'best_p2rank_structure': best_p2rank_id,
                    'p2rank_probability': p2rank_probability,
                    'p2rank_pocket': p2rank_pocket,
                })
            else:
                row.update({
                    'structure': structure_id,
                    'druggability_score': druggability_score,
                    'fpocket_pocket': fpocket_pocket,
                    'p2rank_probability': p2rank_probability,
                    'p2rank_pocket': p2rank_pocket,
                })

            if colabfold_all_models:
                row.update({
                    'colabfold_plddt': colabfold_plddt,
                    'colabfold_druggability_score': CB_druggability_score,
                    'colabfold_fpocket_pocket': CB_fpocket_pocket,
                    'colabfold_p2rank_probability': CB_p2rank_probability,
                    'colabfold_p2rank_pocket': CB_p2rank_pocket,
                })

            rows.append(row)

        final_df = pd.DataFrame(rows)
        # Ensure structure column is stored as string to prevent scientific notation issues
        if 'structure' in final_df.columns:
            final_df['structure'] = final_df['structure'].astype(str)
        final_df.to_csv(final_table_file, sep='\t', index=False)
        print(f'\nFinal structure summary table saved to {final_table_file}')
        print(f'  Total genes: {len(final_df)}')
        print(f'  Genes with structures: {final_df["structure"].notna().sum()}')
        print(f'  Genes with FPocket pockets: {final_df["fpocket_pocket"].notna().sum()}')
        print(f'  Genes with P2Rank pockets: {final_df["p2rank_pocket"].notna().sum()}')
        return final_df
    
    else:
        # Read structure column as string to prevent scientific notation (e.g., 3E59 -> 3e+59)
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        final_df = pd.read_csv(final_table_file, sep='\t', dtype={'structure': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])
        print(f'Final structure summary table loaded from {final_table_file}')
        return final_df
    
def pipeline_structures(output_path, organism_name, specie_taxid, strain_taxid, cpus=multiprocessing.cpu_count(), resolution_cutoff = 3.5, coverage_cutoff=40.0, container_engine='docker', full_mode=False, amber_option=False, gpu_option=False, colabfold=False, colabfold_all_models=False):
    """
    Complete pipeline to obtain and process structures for drug target identification.
    
    This pipeline:
    1. Downloads and processes UniProt proteome data
    2. Maps organism genes to UniProt IDs via BLAST
    3. Downloads PDB and AlphaFold structures
    4. Runs FPocket and P2Rank for druggable pocket detection
    5. Generates final summary tables
    
    :param output_path: Path to the output directory.
    :param organism_name: Name of organism.
    :param specie_taxid: Species-level NCBI Taxonomy ID (e.g., 287 for P. aeruginosa).
    :param strain_taxid: Strain-level NCBI Taxonomy ID (e.g., 208964 for PAO1).
    :param cpus: Number of CPU cores to use. Default is all available cores.
    :param resolution_cutoff: Resolution cutoff for structure selection (default: 3.5 Å).
    :param coverage_cutoff: Coverage cutoff for structure selection (default: 40.0 %).
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :param full_mode: Boolean indicating whether to run the pipeline in full mode (default: False).
    :param amber_option: Boolean indicating whether to use Amber refinement (default: False).
    :param gpu_option: Boolean indicating whether to use GPU acceleration (default: False).
    :param colabfold: Boolean indicating whether to run ColabFold or not (default: False).
    :param colabfold_all_models: Boolean indicating whether to run ColabFold for all proteins (default: False).
    :return: DataFrame with final structure summary table.
    """
    
    print(f'\n{"="*80}')
    print(f'FASTTARGET STRUCTURE ANALYSIS PIPELINE')
    print(f'Organism: {organism_name}')
    print(f'Species TaxID: {specie_taxid} | Strain TaxID: {strain_taxid}')
    print(f'Using {cpus} CPU cores')
    print(f'{"="*80}\n')
    
    # ========== STAGE 1: UniProt Proteome Acquisition ==========
    print(f'\n{"─"*80}')
    print(f'STAGE 1: UNIPROT PROTEOME ACQUISITION AND MAPPING')
    print(f'{"─"*80}')

    structure_dir = os.path.join(output_path, organism_name, 'structures')
    final_table_path = os.path.join(structure_dir, f'{organism_name}_final_structure_summary.tsv')
    
    if not files.file_check(final_table_path):
    
        try:
            print(f'\n[1.1] Downloading UniProt species data (TaxID: {specie_taxid})...')
            download_species_uniprot_data(output_path, organism_name, specie_taxid)
            
            print(f'\n[1.2] Parsing UniProt data into FASTA files...')
            uniprot_dir = os.path.join(output_path, organism_name, 'structures', 'uniprot_files')
            uniprot_file = os.path.join(uniprot_dir, f"uniprot_specie_taxid_{specie_taxid}_data.tsv")
            parse_uniprot_species_data(uniprot_file, specie_taxid, strain_taxid)
            
            print(f'\n[1.3] Clustering species proteome with CD-HIT...')
            cluster_uniprot_specie(output_path, organism_name, specie_taxid)
            
            print(f'\n[1.4] Creating BLAST databases...')
            create_uniprot_blast_db(output_path, organism_name, specie_taxid, strain_taxid)
            
            print(f'\n[1.5] Running BLAST searches against UniProt databases...')
            uniprot_proteome_blast(output_path, organism_name, specie_taxid, strain_taxid, cpus=cpus)
            
            print(f'\n[1.6] Mapping organism genes to UniProt IDs...')
            mapping_dict = uniprot_proteome_mapping(output_path, organism_name, specie_taxid, strain_taxid)
            print(f'    ✓ Mapped {len(mapping_dict)} genes to UniProt IDs')
            
        except Exception as e:
            logging.exception(f'\n    ✗ ERROR in Stage 1: {e}')
            raise
        
        # ========== STAGE 2: Structure Acquisition ==========
        print(f'\n{"─"*80}')
        print(f'STAGE 2: STRUCTURE DOWNLOAD AND ORGANIZATION')
        print(f'{"─"*80}')
        
        try:
            print(f'\n[2.1] Creating directory structure for each gene...')
            create_subfolder_structures(output_path, organism_name)
            
            print(f'\n[2.2] Generating structure summary tables...')
            create_summary_structure_file(output_path, organism_name, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff)
            
            print(f'\n[2.3] Downloading PDB and AlphaFold structures...')
            download_structures(output_path, organism_name)
            
            print(f'\n[2.4] Extracting reference structure chains...')
            if not full_mode:
                get_chain_reference_structure(output_path, organism_name)
            else:
                get_chain_all_pdbs(output_path, organism_name)
            
        except Exception as e:
            logging.exception(f'\n    ✗ ERROR in Stage 2: {e}')
            raise
        
        # ========== STAGE 2.5: ColabFold Model Generation (for missing structures) ==========
        print(f'\n{"─"*80}')
        print(f'STAGE 2.5: COLABFOLD MODEL GENERATION FOR MISSING STRUCTURES')
        print(f'{"─"*80}')
        
        if colabfold and not colabfold_all_models:
            try:
                print(f'\n[2.5.1] Generating ColabFold models for genes without structures...')
                generate_colabfold_missing(output_path, organism_name, amber_option=amber_option, gpu_option=gpu_option)
                print(f'    ✓ ColabFold model generation complete')
                
            except Exception as e:
                logging.exception(f'\n    ✗ ERROR in Stage 2.5: {e}')
                raise

        if colabfold and colabfold_all_models:
            try:
                print(f'\n[2.5.1] Generating ColabFold models for ALL genes in the organism...')
                generate_colabfold_all(output_path, organism_name, amber_option=amber_option, gpu_option=gpu_option)
                print(f'    ✓ ColabFold model generation complete')
                
            except Exception as e:
                logging.exception(f'\n    ✗ ERROR in Stage 2.5: {e}')
                raise
        
        # ========== STAGE 3: Pocket Detection ==========
        print(f'\n{"─"*80}')
        print(f'STAGE 3: DRUGGABLE POCKET DETECTION')
        print(f'{"─"*80}')
        
        try:
            print(f'\n[3.1] Running FPocket for all structures...')
            structures_dir = os.path.join(output_path, organism_name, 'structures')
            pockets_finder_for_all_loci(output_path, organism_name, container_engine=container_engine, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff)
            
            print(f'\n[3.2] Running P2Rank for all structures...')
            p2rank_finder_for_all_loci(output_path, organism_name, cpus, container_engine=container_engine, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models, resolution_cutoff=resolution_cutoff, coverage_cutoff=coverage_cutoff)
            
            print(f'\n[3.3] Merging structure and pocket data...')
            merged_data = merge_structure_data(output_path, organism_name, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models)
            print(f'    ✓ Processed {len(merged_data)} genes')
            
            print(f'\n[3.4] Creating final summary table...')
            final_df = final_structure_table(output_path, organism_name, full_mode=full_mode, colabfold=colabfold, colabfold_all_models=colabfold_all_models)
            
        except Exception as e:
            logging.exception(f'\n    ✗ ERROR in Stage 3: {e}')
            raise
        
        # ========== STAGE 4: Generate Report ==========
        print(f'\n{"─"*80}')
        print(f'STAGE 4: GENERATING STRUCTURE ANALYSIS REPORT')
        print(f'{"─"*80}')
        
        try:
            generate_structure_report(output_path, organism_name)
        except Exception as e:
            logging.exception(f'\n    ✗ ERROR in Stage 4 (Report generation): {e}')
            # Don't raise - report generation is non-critical
        
        # ========== Pipeline Complete ==========
        print(f'\n{"="*80}')
        print(f'Pipeline finished')
        print(f'{"="*80}')
        
        print(f'\nResults saved to: {final_table_path}')
        print(f'Structure data: {os.path.join(structure_dir, f"{organism_name}_structure_data.json")}')
    
    else:
        print(f'Final structure summary table already exists at {final_table_path}, loading existing data.')
        # Keep "NA" as string (valid chain name) instead of treating it as NaN
        final_df = pd.read_csv(final_table_path, sep='\t', dtype={'structure': str}, keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])
        
        # Generate report even if table already exists
        try:
            print(f'\nGenerating structure analysis report...')
            generate_structure_report(output_path, organism_name)
        except Exception as e:
            logging.exception(f'Error generating report: {e}')
        
    return final_df


def get_reference_structure_path(output_path, organism_name, locus_tag):
    """
    Get the file path of the reference structure for a given locus_tag.
    
    This is a convenience wrapper around find_structures_for_locus() that takes
    output_path, organism_name, and locus_tag as parameters.
    
    Selection priority:
    1) Structure marked as reference in *_structure_summary.tsv (PDB/AlphaFold/ColabFold)
    2) Fallback via find_structures_for_locus()
    3) None if no reference structure found
    
    :param output_path: Path to output directory.
    :param organism_name: Name of organism.
    :param locus_tag: Locus tag identifier.
    
    :return: Absolute path to reference structure file, or None if not found.
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    locus_dir = os.path.join(structure_dir, locus_tag)
    
    # Check if locus directory exists
    if not os.path.isdir(locus_dir):
        return None
    
    def _first_existing(patterns):
        for pattern in patterns:
            matches = sorted(set(glob.glob(pattern, recursive=True)))
            if matches:
                return matches[0]
        return None

    def _resolve_from_summary(ref_row):
        structure_type = str(ref_row.get('structure_type', '')).strip().lower()
        structure_id = str(ref_row.get('structure_id', '')).strip()
        uniprot_id = str(ref_row.get('uniprot_id', '')).strip()
        chain_field = str(ref_row.get('chain', '')).strip()

        search_roots = [locus_dir]
        if uniprot_id and uniprot_id.lower() not in ('nan', 'none'):
            uniprot_dir = os.path.join(locus_dir, uniprot_id)
            if os.path.isdir(uniprot_dir):
                search_roots.insert(0, uniprot_dir)

        chains = []
        if chain_field and chain_field.lower() not in ('nan', 'none'):
            chains = [c.strip() for c in chain_field.split(';') if c.strip()]

        patterns = []

        if structure_type == 'pdb':
            for root in search_roots:
                # Preferred: extracted reference chain(s)
                patterns.append(os.path.join(root, '**', f'PDB_{structure_id}_*_ref.pdb'))
                patterns.append(os.path.join(root, '**', f'PDB_{structure_id}_ref.pdb'))
                # Fallback: chain-extracted files generated in full mode
                for chain in chains:
                    patterns.append(os.path.join(root, '**', f'PDB_{structure_id}_chain_{chain}.pdb'))
                patterns.append(os.path.join(root, '**', f'PDB_{structure_id}_chain_*.pdb'))
                # Last fallback: raw structure files
                patterns.append(os.path.join(root, '**', f'PDB_{structure_id}.pdb'))
                patterns.append(os.path.join(root, '**', f'PDB_{structure_id}.cif'))

        elif structure_type == 'alphafold':
            for root in search_roots:
                if uniprot_id and uniprot_id.lower() not in ('nan', 'none'):
                    patterns.append(os.path.join(root, '**', f'AF_{uniprot_id}.pdb'))
                patterns.append(os.path.join(root, '**', f'AF_{structure_id}.pdb'))
                patterns.append(os.path.join(root, '**', 'AF_*.pdb'))

        elif structure_type == 'colabfold':
            for root in search_roots:
                patterns.append(os.path.join(root, '**', f'{structure_id}.pdb'))
                patterns.append(os.path.join(root, '**', 'CB_*.pdb'))

        return _first_existing(patterns)

    summary_table_path = os.path.join(locus_dir, f'{locus_tag}_structure_summary.tsv')
    if files.file_check(summary_table_path):
        try:
            summary_df = pd.read_csv(
                summary_table_path,
                sep='\t',
                dtype={'structure_id': str, 'chain': str, 'uniprot_id': str},
                keep_default_na=False,
                na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null']
            )
            if 'is_reference' in summary_df.columns:
                ref_mask = summary_df['is_reference'].astype(str).str.lower().isin(['true', '1', 'yes'])
                ref_rows = summary_df[ref_mask]
                if not ref_rows.empty:
                    ref_path = _resolve_from_summary(ref_rows.iloc[0])
                    if ref_path:
                        return ref_path
                    logging.warning(f"Reference row found in summary but file not resolved for {locus_tag}. Falling back to find_structures_for_locus resolver.")
        except Exception as e:
            logging.warning(f"Could not parse summary table {summary_table_path}: {e}. Falling back to find_structures_for_locus() resolver.")

    # Fallback for backward compatibility
    reference_data = find_structures_for_locus(locus_dir, colabfold=False, colabfold_all_models=False)
    if reference_data:
        return reference_data[0]
    return None


def get_all_reference_structures(output_path, organism_name, path_mode=True):
    """
    Get a dictionary mapping all locus_tags to their reference structure paths.
    
    This function iterates through all locus_tag directories and finds their
    reference structures, returning a complete mapping.
    
    :param output_path: Path to output directory.
    :param organism_name: Name of organism.
    :param path_mode: If True, return full file paths. If False, return only structure names.
    
    :return: Dictionary with locus_tag as key and reference structure path as value.
             Locus tags without structures will have None as value.
    """
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    
    # Get all locus_tags from genome
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)
    
    reference_structures = {}
    
    for locus_tag in all_locus_tags:
        if path_mode:
            ref_path = get_reference_structure_path(output_path, organism_name, locus_tag)
            if ref_path:
                reference_structures[locus_tag] = ref_path
            else:
                reference_structures[locus_tag] = None
        else:
            #get the name of the reference structure only
            ref_path = get_reference_structure_path(output_path, organism_name, locus_tag)
            if ref_path:
                ref_name = os.path.basename(ref_path).split('.')[0]
                reference_structures[locus_tag] = ref_name
            else:
                reference_structures[locus_tag] = None

    return reference_structures


def generate_structure_report(output_path, organism_name):
    """
    Generate a comprehensive structure analysis report.
    
    Analyzes the final structure summary table and creates a detailed text report
    with statistics about structure availability and pocket predictions.
    
    :param output_path: Path to the output directory
    :param organism_name: Name of the organism
    :return: Path to the generated report file
    """
    
    structure_dir = os.path.join(output_path, organism_name, 'structures')
    final_table_path = os.path.join(structure_dir, f'{organism_name}_final_structure_summary.tsv')
    report_path = os.path.join(structure_dir, f'{organism_name}_STRUCTURE_REPORT.txt')
    
    # Load the final structure summary table
    if not os.path.exists(final_table_path):
        logging.error(f"Final structure summary table not found at {final_table_path}")
        return None
    
    try:
        df = pd.read_csv(final_table_path, sep='\t', dtype={'structure': str}, 
                        keep_default_na=False, na_values=['', '#N/A', '#N/A N/A', '#NA', 
                        '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', 
                        '<NA>', 'N/A', 'NULL', 'NaN', 'n/a', 'nan', 'null'])
    except Exception as e:
        logging.error(f"Error reading final structure summary table: {e}")
        return None
    
    # Calculate statistics
    total_proteins = len(df)
    
    # Count proteins with structures
    proteins_with_pdb = 0
    proteins_with_alphafold = 0
    proteins_with_colabfold = 0
    proteins_with_structures = set()
    
    for idx, row in df.iterrows():
        structure = str(row.get('structure', '')).strip()
        
        if not structure or structure.lower() in ['nan', 'none', '']:
            continue
            
        proteins_with_structures.add(idx)
        
        # Check for PDB (starts with 'PDB_')
        if 'PDB_' in structure:
            proteins_with_pdb += 1
        
        # Check for AlphaFold (starts with 'AF_')
        if 'AF_' in structure:
            proteins_with_alphafold += 1
        
        # Check for ColabFold (starts with 'CB_')
        if 'CB_' in structure:
            proteins_with_colabfold += 1
    
    proteins_without_structures = total_proteins - len(proteins_with_structures)
    
    # Count proteins with pockets
    proteins_with_pockets = 0
    proteins_with_fpocket = 0
    proteins_with_p2rank = 0
    
    fpocket_col = 'fpocket_pocket'
    p2rank_col = 'p2rank_pocket'
    
    # Check for ColabFold versions if they exist
    colabfold_fpocket_col = 'colabfold_fpocket_pocket'
    colabfold_p2rank_col = 'colabfold_p2rank_pocket'
    
    for idx, row in df.iterrows():
        has_fpocket = False
        has_p2rank = False
        
        # Check standard pocket columns
        if fpocket_col in df.columns:
            fpocket = str(row.get(fpocket_col, '')).strip()
            if fpocket and fpocket.lower() not in ['nan', 'none', '']:
                has_fpocket = True
                proteins_with_fpocket += 1
        
        if p2rank_col in df.columns:
            p2rank = str(row.get(p2rank_col, '')).strip()
            if p2rank and p2rank.lower() not in ['nan', 'none', '']:
                has_p2rank = True
                proteins_with_p2rank += 1
        
        # Check ColabFold pocket columns
        if colabfold_fpocket_col in df.columns:
            cf_fpocket = str(row.get(colabfold_fpocket_col, '')).strip()
            if cf_fpocket and cf_fpocket.lower() not in ['nan', 'none', '']:
                has_fpocket = True
                if not (fpocket_col in df.columns and 
                       str(row.get(fpocket_col, '')).strip() and 
                       str(row.get(fpocket_col, '')).strip().lower() not in ['nan', 'none', '']):
                    proteins_with_fpocket += 1
        
        if colabfold_p2rank_col in df.columns:
            cf_p2rank = str(row.get(colabfold_p2rank_col, '')).strip()
            if cf_p2rank and cf_p2rank.lower() not in ['nan', 'none', '']:
                has_p2rank = True
                if not (p2rank_col in df.columns and 
                       str(row.get(p2rank_col, '')).strip() and 
                       str(row.get(p2rank_col, '')).strip().lower() not in ['nan', 'none', '']):
                    proteins_with_p2rank += 1
        
        if has_fpocket or has_p2rank:
            proteins_with_pockets += 1
    
    proteins_without_pockets = total_proteins - proteins_with_pockets
    
    # Generate the report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("FASTTARGET STRUCTURE ANALYSIS REPORT".center(80))
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append(f"Organism: {organism_name}")
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    report_lines.append("=" * 80)
    report_lines.append("STRUCTURE AVAILABILITY SUMMARY")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append(f"Total number of proteins analyzed: {total_proteins}")
    report_lines.append("")
    
    # Structures section
    report_lines.append("-" * 80)
    report_lines.append("STRUCTURES")
    report_lines.append("-" * 80)
    report_lines.append(f"Proteins WITH any structure:          {len(proteins_with_structures):6d}  ({len(proteins_with_structures)/total_proteins*100:5.1f}%)")
    report_lines.append(f"  └─ With PDB structures:             {proteins_with_pdb:6d}  ({proteins_with_pdb/total_proteins*100:5.1f}%)")
    report_lines.append(f"  └─ With AlphaFold structures:       {proteins_with_alphafold:6d}  ({proteins_with_alphafold/total_proteins*100:5.1f}%)")
    report_lines.append(f"  └─ With ColabFold structures:       {proteins_with_colabfold:6d}  ({proteins_with_colabfold/total_proteins*100:5.1f}%)")
    report_lines.append("")
    report_lines.append(f"Proteins WITHOUT any structure:       {proteins_without_structures:6d}  ({proteins_without_structures/total_proteins*100:5.1f}%)")
    report_lines.append("")
    
    # Pockets section
    report_lines.append("-" * 80)
    report_lines.append("POCKETS")
    report_lines.append("-" * 80)
    report_lines.append(f"Proteins WITH pockets:                {proteins_with_pockets:6d}  ({proteins_with_pockets/total_proteins*100:5.1f}%)")
    
    # Only show FPocket and P2Rank if they exist
    if proteins_with_fpocket > 0 or 'fpocket_pocket' in df.columns:
        report_lines.append(f"  └─ With FPocket predictions:        {proteins_with_fpocket:6d}  ({proteins_with_fpocket/total_proteins*100:5.1f}%)")
    
    if proteins_with_p2rank > 0 or 'p2rank_pocket' in df.columns:
        report_lines.append(f"  └─ With P2Rank predictions:         {proteins_with_p2rank:6d}  ({proteins_with_p2rank/total_proteins*100:5.1f}%)")
    
    report_lines.append("")
    report_lines.append(f"Proteins WITHOUT pockets:             {proteins_without_pockets:6d}  ({proteins_without_pockets/total_proteins*100:5.1f}%)")
    report_lines.append("")
    report_lines.append("=" * 80)
    
    # Write report to file
    try:
        with open(report_path, 'w') as f:
            f.write('\n'.join(report_lines))
        
        logging.info(f"Structure report generated: {report_path}")
        
        return report_path
        
    except Exception as e:
        logging.error(f"Error writing report to file: {e}")
        return None

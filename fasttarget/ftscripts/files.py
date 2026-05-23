import os
import json
import sys
import pandas as pd
import logging
import math

def file_to_list(file_path):
    
    """
    Read a text file and return a list with each line as an element.

    :param file_path: The name of the text file to read from.

    :return: List with each line as an element.
    
    """
    
    my_list = []
    
    try:
        with open(file_path, 'r') as file:
            my_list = [line.strip() for line in file]
        return my_list
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred while reading the file: {e}")

def list_to_file(file_path, my_list):

    """
    Write a list to a .txt file. Each element as a new line.

    :param file_path: Path of .txt file.
    :param my_list: List to covert.

    """

    with open(file_path, 'w') as file:
        for item in my_list:
            file.write(str(item) + '\n')

def file_check(file_path):

    """
    Check if a file exists and is not empty.

    :param file_path: Path of the file.

    :return: True if the file exists and it is not empty, False otherwise.

    """

    file_res = False

    if file_path:

        # Check if the file exists
        if not os.path.isfile(file_path):
            file_res = False
        else:
            # Check if the file is empty
            if os.path.getsize(file_path) > 0:
                file_res = True   
            else:
                file_res = False
                
    return file_res

def json_to_dict (file_path):

    """
    Read a .json file to a dict.

    :param file_path: Path of .json file.

    :return: Dictionary representing JSON object.

    """

    if os.path.exists(file_path):
        # Read dictionary from the file_path given
        with open(file_path, 'r') as file:
            loaded_dict = json.load(file)
    else:
        logging.error(f"The file '{file_path}' not found.")
        loaded_dict = None
    return loaded_dict

def jsonl_to_dict(file_path):
    """
    Read a .jsonl file to a list of dicts.

    :param file_path: Path of .jsonl file.

    :return: List of dictionaries representing JSON objects.
    """

    if os.path.exists(file_path):
        loaded_dicts = []
        with open(file_path, 'r') as file:
            for line in file:
                loaded_dicts.append(json.loads(line.strip()))
    else:
        logging.error(f"The file '{file_path}' not found.")
        loaded_dicts = None
    return loaded_dicts

def dict_to_json(output_path, file_name, my_dict):

    """
    Write a .json file from a a dictionary.

    :param output_path:  Path to save the .json file.
    :param file_name: Name of the .json file.
    :param my_dict: Dictionary to save.

    """

    def _sanitize_for_json(obj):
        if isinstance(obj, dict):
            return {k: _sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize_for_json(v) for v in obj]
        if isinstance(obj, tuple):
            return [_sanitize_for_json(v) for v in obj]
        if hasattr(obj, "item"):
            return _sanitize_for_json(obj.item())
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj

    full_path = os.path.join(output_path, file_name)
    
    if os.path.exists(output_path):
        with open(full_path, 'w') as file:
            json.dump(_sanitize_for_json(my_dict), file, allow_nan=False)
        print(f"File '{full_path}' saved.")
    else:
        print(f"The directory '{output_path}' does not exist.")

def create_organism_subfolders(output_path, organism_name):

    """
    Create subfolders for an organism. 
    
    :param output_path: Output path where the organism folder will be created.
    :param organism_names: Name of the organism.
    """
    organism_dir = os.path.join(output_path, organism_name)

    if not os.path.exists(organism_dir):
        os.makedirs(organism_dir, exist_ok=True)
        print(f'Created directory: {organism_dir}')
    
    list_dir = ['offtarget', 'metabolism', 'structures', 'essentiality', 'conservation', 'metadata', 'genome', 'localization']
    # Subfolders
    for dir in list_dir:
        dir_path = os.path.join(organism_dir, dir)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            print(f"Created directory: {dir_path}")

def read_blast_output(file_path, len=False):
    """
    Read BLASTP output file and return a pandas DataFrame.

    :param file_path: File path of blast output file.
    :len: If True, the length of the query and subject sequences will be added to the DataFrame.

    :return: Pandas DataFrame with blast output.
    """

    if os.path.exists(file_path):
        blast_output_df = pd.read_csv(file_path, sep='\t', header=None)

        # Columns used for blastp
        blast_columns = [
        "qseqid",   # query or source (gene) sequence id
        "sseqid",   # subject or target (reference genome) sequence id
        "pident",   # percentage of identical positions
        "length",   # alignment length (sequence overlap)
        "mismatch", # number of mismatches
        "gapopen",  # number of gap openings
        "qstart",   # start of alignment in query
        "qend",     # end of alignment in query
        "sstart",   # start of alignment in subject
        "send",     # end of alignment in subject
        "evalue",   # expect value
        "bitscore", # bit score
        "qcovhsp",  # Query Coverage hsp
        "qcovs"     # Query Coverage full
        ]

        if len: #add qlen and slen to columns
            blast_columns.extend(['qlen', 'slen'])

        blast_output_df.columns = blast_columns

        return blast_output_df
    
    else:
        print(f'File {file_path} not found.')

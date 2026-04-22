
from ftscripts import programs, metadata, files
import os
import pandas as pd
import multiprocessing

def essential_deg_blast(databases_path, output_path, organism_name, cpus=multiprocessing.cpu_count()):

    """
    Runs NCBI BLASTP against DEG bacterial proteome.
    This function uses the `run_blastp` function from the `programs` module.
    It uses the DEG_DB database created by the `index_db_blast_deg` function from the `databases` module.
    The blast output is saved in the 'essentiality' folder of the organism directory.

    :param databases_path: Path where the DEG database is stored.
    :param output_path: organism output path.
    :param organism_name: Name of the organism.
    :param cpus: Number of threads (CPUs) to use in blast search.
    
    """

    #Database files
    deg_index_path = os.path.join(databases_path, 'DEG_DB')

    #Organism files
    organism_path = os.path.join(output_path, organism_name)
    organism_prot_seq_path = os.path.join(organism_path, f'genome/{organism_name}.faa')

    essentiality_path = os.path.join(organism_path, 'essentiality')
    blast_output_path = os.path.join(essentiality_path, 'deg_blast.tsv')

    programs.run_blastp(
        blastdb= deg_index_path,
        query= organism_prot_seq_path,
        output=blast_output_path,
        evalue= '1e-5',
        outfmt= '6 std qcovhsp qcovs',
        cpus=cpus
    )

def deg_parse (output_path, organism_name, identity_filter, coverage_filter):

    """
    Parse NCBI BLASTP results against DEG bacterial proteome, stored in the file 'deg_blast.tsv'.
    Filters results based on identity and coverage thresholds, and obtains the proteins that has at least one hit with DEG.
    Returns a list with locus_tags that have at least one hit with DEG, and a DataFrame with all locus_tags from the genome and a TRUE/FALSE value.
    The DataFrame is created using the `metadata_table_bool` function from the `metadata` module.
    
    :param output_path: organism output path.
    :param organism_name: Name of organism.
    :param identity_filter: Value of % of Identity filter. Keeps results above this value in column pident.
    :param coverage_filter: Value of query coverage filter. Keeps results above this value in column qcovs.
    
    :return: List with locus_tags that have at least one hit in DEG.
    :return: DataFrame with all locus_tags from genome and a TRUE/FALSE value.
    """

    essentiality_path = os.path.join(output_path, organism_name, 'essentiality')
    deg_blast_output = os.path.join(essentiality_path, 'deg_blast.tsv')
    deg_results = os.path.join(essentiality_path, 'hit_in_deg.tsv')

    if not files.file_check(deg_results):
        blast_output_df = files.read_blast_output(deg_blast_output)

        #Filter % identity and coverage
        filtered_df = blast_output_df[(blast_output_df['pident'] > identity_filter) 
                                    & (blast_output_df['qcovs'] > coverage_filter)]

        unique_values = filtered_df['qseqid'].unique()
        deg_hits = unique_values.tolist()

        df_deg = metadata.metadata_table_bool(output_path, organism_name, deg_hits, 
                                            'hit_in_deg', essentiality_path)
    else:
        print('DEG analysis already done, output file found')
        print(deg_results)
        df_deg = pd.read_csv(deg_results, sep='\t', header=0)
        
    return df_deg

    

from ftscripts import programs, metadata, files, structures
import os
import json
import pandas as pd
import multiprocessing
import glob
from tqdm import tqdm
import logging

def human_offtarget_blast (databases_path, output_path, organism_name, cpus=multiprocessing.cpu_count()):

    """
    Runs NCBI BLASTP against the human proteome.
    This function uses the `run_blastp` function from the `programs` module.
    It uses the HUMAN_DB database created by the `index_db_blast_human` function from the `databases` module.
    The blast output is saved in the 'offtarget' folder of the organism directory.

    :param databases_path: Directory where HUMAN databases are stored.
    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param cpus: Number of threads (CPUs) to use in the blast search.
    
    """

    #Database files
    humanprot_index_path = os.path.join(databases_path, 'HUMAN_DB')

    #Organism files
    organism_path = os.path.join(output_path, organism_name)
    organism_prot_seq_path = os.path.join(organism_path, f'genome/{organism_name}.faa')

    offtarget_path = os.path.join(organism_path, 'offtarget')
    blast_output_path = os.path.join(offtarget_path, 'human_offtarget_blast.tsv')

    programs.run_blastp(
        blastdb= humanprot_index_path,
        query= organism_prot_seq_path,
        output=blast_output_path,
        evalue= '1e-5',
        outfmt= '6 std qcovhsp qcovs',
        cpus=cpus
    )

def microbiome_offtarget_blast_species (databases_path, output_path, organism_name, cpus=multiprocessing.cpu_count()):
    """
    Runs Diamond BLASTP of the organism proteome against each genome in the microbiome species catalogue.
    Each genome in the species catalogue is stored as a subdirectory under `databases/species_catalogue`,
    containing its own .faa file and BLAST index.

    For each genome, the BLAST output is stored in the 'offtarget' folder of the organism directory,
    with one result file per genome. The process can be resumed if interrupted.

    :param databases_path: Path where the species catalogue databases are stored.
    :param output_path: Path of the organism output.
    :param organism_name: Name of the organism (folder name under 'organism').
    :param cpus: Number of threads (CPUs) to use in the BLAST search.
    """

    # Path to species catalogue
    species_databases_path = os.path.join(databases_path, "species_catalogue")

    # Path to organism proteome (.faa file)
    organism_path = os.path.join(output_path, organism_name)
    organism_prot_seq_path = os.path.join(organism_path, "genome", f"{organism_name}.faa")

    # Output folder
    offtarget_path = os.path.join(organism_path, "offtarget", "species_blast_results")
    os.makedirs(offtarget_path, exist_ok=True)

    # Iterate over each genome (subfolder with its own indexed faa)
    for genome_dir in sorted(os.listdir(species_databases_path)):
        genome_path = os.path.join(species_databases_path, genome_dir)
        
        if not os.path.isdir(genome_path):
            continue

        # Output file for this genome
        blast_output_path = os.path.join(offtarget_path, f"{genome_dir}_offtarget.tsv")

        # Skip if already exists (resume functionality)
        if os.path.exists(blast_output_path):
            print(f"✔️ Skipping {genome_dir}, result already exists")
            continue

        # Run Diamond BLASTP for this genome
        print(f"🔹 Running Diamond BLAST against {genome_dir}")
        genome_db = os.path.join(genome_path, f'{genome_dir}_DB')
        
        programs.run_diamond_blastp(
            blastdb=genome_db,                  # index db                
            query=organism_prot_seq_path,       # organism proteome
            output=blast_output_path,           # result per genome
            evalue="1e-5",
            outfmt="6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore qcovhsp",
            cpus=cpus
        )

def microbiome_offtarget_blast_allproteins (databases_path, output_path, organism_name, cpus=multiprocessing.cpu_count()):

    """
    Runs ncbi blastp against microbiome proteome.
    This function uses the `run_blastp` function from the `programs` module.
    It uses the MICROBIOME_DB database created by the `index_db_blast_microbiome` function from the `databases` module.
    The blast output is saved in the 'offtarget' folder of the organism directory.

    :param databases_path: Directory where MICROBIOME database is stored.
    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param cpus: Number of threads (CPUs) to use in the blast search.
    
    """
    
    #Database files
    species_databases_path = os.path.join(databases_path,  'species_catalogue')
    microbiome_index_path = os.path.join(species_databases_path, 'MICROBIOME_DB')

    #Organism files
    organism_path = os.path.join(output_path, organism_name)
    organism_prot_seq_path = os.path.join(organism_path, f'genome/{organism_name}.faa')

    offtarget_path = os.path.join(organism_path, 'offtarget')
    blast_output_path = os.path.join(offtarget_path, 'microbiome_offtarget_blast.tsv')

    programs.run_diamond_blastp(
        blastdb= microbiome_index_path,
        query= organism_prot_seq_path,
        output=blast_output_path,
        evalue= '1e-5',
        outfmt= '6 std qcovhsp qcovs',
        cpus=cpus
    )

def human_offtarget_parse (output_path, organism_name):

    """
    Parse NCBI BLASTP results against human proteome, stored in the file 'human_offtarget_blast.tsv'.
    Obtains the hit with the highest percentage of identity for each locus_tag.
    Returns a dictionary with locus_tag as key and highest percentage of identity as value, 
    and a DataFrame with all locus_tags from the genome and their respective values.
    The DataFrame is created using the `metadata_table_with_values` function from the `metadata` module.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    
    :return: Dictionary with locus_tag as key and highest percentage of identity value.
    :return: DataFrame with all locus_tags from the genome and their respective values.
    """

    offtarget_path = os.path.join(output_path, organism_name, 'offtarget')
    human_blast_output = os.path.join(offtarget_path, 'human_offtarget_blast.tsv')
    human_results = os.path.join(offtarget_path, 'human_offtarget.tsv')

    if not files.file_check(human_results):
        blast_output_df = files.read_blast_output(human_blast_output)

        highest_pident_values = {}

        for index,row in blast_output_df.iterrows():
            qseqid = row['qseqid']
            pident = row['pident']

            if qseqid not in highest_pident_values or pident > highest_pident_values[qseqid]:
                highest_pident_values[qseqid] = pident

        df_human = metadata.metadata_table_with_values(output_path, organism_name, highest_pident_values, 
                                            'human_offtarget', offtarget_path, 'no_hit')
    else:
        print('Human offtarget analysis already done, output file found')
        print(human_results)
        df_human = pd.read_csv(human_results, sep='\t', header=0)

    return df_human

def microbiome_species_parse(databases_path, output_path, organism_name, identity_filter, coverage_filter):
    """
    Parse Diamond BLASTP results against all genomes in the microbiome species catalogue.
    Each genome has its own BLAST output file under 'offtarget' folder of the organism.

    For each protein (qseqid) of the organism, this function determines in which genomes
    it has at least one hit passing the identity and coverage filters.

    :param output_path: Directory of the organism output.
    :param databases_path: Base path where MICROBIOME database is stored.
    :param organism_name: Name of the organism.
    :param identity_filter: Percentage identity filter value. Keeps results above this value in the pident column.
    :param coverage_filter: Query coverage filter value. Keeps results above this value in the qcovs column.

    Returns:
        - df_microbiome_norm: DataFrame with one row per protein and a column with normalized counts
        - df_microbiome_counts: DataFrame with one row per protein and a column with number of genomes with hits
        - df_microbiome_total_genomes: DataFrame with one row per protein and a column with total number of genomes analyzed
    """

    offtarget_path = os.path.join(output_path, organism_name, "offtarget", "species_blast_results")

    protein_hits = {}  # dict: protein_id -> set of genomes
    genome_files = [f for f in os.listdir(offtarget_path) if f.endswith("_offtarget.tsv")]
    total_outputs = len(genome_files)

    species_path = os.path.join(databases_path, "species_catalogue")
    total_genomes = len([d for d in os.listdir(species_path) if os.path.isdir(os.path.join(species_path, d))])

    if total_outputs == 0:
        print(f"Error: No microbiome species BLAST results found in {offtarget_path}. Please run the microbiome_offtarget_blast_species function first.")
        return pd.DataFrame()

    if total_outputs < total_genomes:                                                                   
        print(f"Warning: Only {total_outputs} out of {total_genomes} microbiome species BLAST results found in {offtarget_path}.")
        print("Some genomes may be missing or the process was interrupted.")
        print("Proceeding with available results...")

    microbiome_results = os.path.join(offtarget_path, 'gut_microbiome_offtarget_counts.tsv')
    microbiome_results_norm = os.path.join(offtarget_path, 'gut_microbiome_offtarget_norm.tsv')
    microbiome_results_genomes = os.path.join(offtarget_path, 'gut_microbiome_genomes_analyzed.tsv')

    if files.file_check(microbiome_results):
        print('Microbiome species offtarget analysis already done, output file found')
        print(microbiome_results)
        df_hit_totals = pd.read_csv(microbiome_results, sep='\t', header=0)
        df_microbiome_norm = pd.read_csv(microbiome_results_norm, sep='\t', header=0)
        df_total_genomes = pd.read_csv(microbiome_results_genomes, sep='\t', header=0)

    else:
        print(f"Parsing microbiome species BLAST results...")
        print(f"Total genomes in species catalogue: {total_genomes}")

        for file in tqdm(sorted(genome_files), desc="Parsing microbiome species BLAST results"):
            genome_name = file.replace("_offtarget.tsv", "")
            blast_output_path = os.path.join(offtarget_path, file)

            if os.stat(blast_output_path).st_size == 0:
                continue

            df = pd.read_csv(blast_output_path, sep="\t", header=None)

            # Diamond outfmt: "6 std qcovhsp"
            df.columns = [
                "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
                "qstart", "qend", "sstart", "send", "evalue", "bitscore",
                "qcovhsp"
            ]

            filtered_df = df[(df["pident"] > identity_filter) & (df["qcovhsp"] > coverage_filter)]

            for qseqid in filtered_df["qseqid"].unique():
                protein_hits.setdefault(qseqid, set()).add(genome_name)

        # Convert sets to sorted lists
        protein_hits = {prot: sorted(list(genomes)) for prot, genomes in protein_hits.items()}

        # Normalized counts: number of genomes with hits / total genomes
        protein_hit_counts = {
            prot: len(genomes) / total_genomes if total_genomes > 0 else 0
            for prot, genomes in protein_hits.items()
        }

        # Number of genomes with hits
        protein_hit_totals = {
            prot: len(genomes)
            for prot, genomes in protein_hits.items()
        }

        # Total number of genomes analyzed for each protein
        protein_total_genomes = {
            prot: total_genomes
            for prot in protein_hits.keys()
        }


        # Build DataFrame 
        df_microbiome = metadata.metadata_table_with_values(output_path, organism_name, protein_hits, 
                                                'gut_microbiome_offtarget', offtarget_path, 'no_hit')

        df_microbiome_norm = metadata.metadata_table_with_values(output_path, organism_name, protein_hit_counts,
                                                'gut_microbiome_offtarget_norm', offtarget_path, 0)
        
        df_hit_totals = metadata.metadata_table_with_values(output_path, organism_name, protein_hit_totals,
                                                'gut_microbiome_offtarget_counts', offtarget_path, 0)

        df_total_genomes = metadata.metadata_table_with_values(output_path, organism_name, protein_total_genomes,
                                                'gut_microbiome_genomes_analyzed', offtarget_path, total_genomes)

    return df_microbiome_norm, df_hit_totals, df_total_genomes


def microbiome_protein_clusters_parse (output_path, organism_name, identity_filter, coverage_filter):

    """
    Parse NCBI BLASTP results against microbiome proteome, stored in the file 'microbiome_offtarget_blast.tsv'.
    Filters results based on identity and coverage thresholds, then counts occurrences of each locus_tag.
    Returns a dictionary with normalized counts of each locus_tag that has at least one hit with UHGP90, 
    and a DataFrame with all locus_tags from the genome and their respective values.
    The DataFrame is created using the `metadata_table_with_values` function from the `metadata` module.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param identity_filter: Percentage identity filter value. Keeps results above this value in the pident column.
    :param coverage_filter: Query coverage filter value. Keeps results above this value in the qcovs column.
    
    :return: Dictionary with normalized counts of locus_tags that have at least one hit with UHGP90.
    :return: DataFrame with all locus_tags from the genome and their respective normalized values.
    """

    offtarget_path = os.path.join(output_path, organism_name, 'offtarget')
    microbiome_blast_output = os.path.join(offtarget_path, 'microbiome_offtarget_blast.tsv')
    microbiome_results = os.path.join(offtarget_path, 'gut_microbiome_offtarget.tsv')

    if not files.file_check(microbiome_results):

        blast_output_df = files.read_blast_output(microbiome_blast_output)

        #Filter % identity and coverage
        filtered_df = blast_output_df[(blast_output_df['pident'] > identity_filter) 
                                    & (blast_output_df['qcovs'] > coverage_filter)]

        value_counts = filtered_df['qseqid'].value_counts()
        max_count = value_counts.max()
        norm_counts = value_counts / max_count

        normalized_counts_dict = norm_counts.to_dict()

        df_microbiome = metadata.metadata_table_with_values(output_path, organism_name, normalized_counts_dict, 
                                            'gut_microbiome_offtarget', offtarget_path, 'no_hit')

    else:
        print('Microbiome offtarget analysis already done, output file found')
        print(microbiome_results)
        df_microbiome = pd.read_csv(microbiome_results, sep='\t', header=0)
        
    return df_microbiome


def run_foldseek_human_structures (databases_path, output_path, organism_name, container_engine='docker'):

    """
    Runs Foldseek easy-search against unified human reference structures database.
    Uses ONLY the reference structures for each locus_tag.
    
    Reference structures are obtained via structures.get_all_reference_structures():
    - PDB reference structures: PDB_{uniprot}_{pdb_id}_{chain}.pdb (extracted chains)
    - AlphaFold models: AF_{uniprot}.pdb (full predictions)
    
    Each reference structure is searched against the unified human reference database
    containing both PDB and AlphaFold structures.

    :param output_path: Directory of the organism output.
    :param databases_path: Directory where FOLDSEEK structure databases are stored.
    :param organism_name: Name of the organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :return: Dictionary with locus_tag as key and path to foldseek results file as value.
    """
    foldseek_results_mapping = {}

    print(f'\n{"="*80}')
    print('FOLDSEEK HUMAN OFFTARGET ANALYSIS')
    print(f'{"="*80}\n')

    # Human unified reference database (PDB + AlphaFold structures)
    # DB is created in DB_foldseek subdirectory by programs.run_foldseek_create_index_db
    db_human_path = os.path.join(databases_path, 'human_structures', 'DB_foldseek')

    # Get all reference structures using helper function
    print('Getting reference structures for all locus_tags...')
    reference_dict = structures.get_all_reference_structures(output_path, organism_name, path_mode=True)
    
    # Filter out None values (locus_tags without structures)
    reference_dict = {k: v for k, v in reference_dict.items() if v is not None}
    
    print(f'Found {len(reference_dict)} locus_tags with reference structures')
    
    # Offtarget path - create directory before any early returns
    offtarget_path = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtarget_path, 'foldseek_results')

    if not os.path.exists(foldseek_results_path):
        os.makedirs(foldseek_results_path, exist_ok=True)
    
    if not reference_dict:
        print('ERROR: No reference structures found. Make sure to run structures pipeline first.')
        return {}

    # Run Foldseek for each reference structure
    success_count = 0
    error_count = 0
    skipped_count = 0
    
    for locus_tag, struct_path in reference_dict.items():
        struct_name = os.path.basename(struct_path)
        struct_dir = os.path.dirname(struct_path)
        
        print(f'\n[{locus_tag}] Processing {struct_name}')
        
        # Search against unified human reference database (PDB + AlphaFold)
        try:
            programs.run_foldseek_search(struct_dir, db_human_path, 'DB_human_reference', struct_name, foldseek_results_path, container_engine=container_engine)
            
            # Validate output file exists before reporting success
            struct_basename = struct_name.split('.')[0]
            result_file = os.path.join(foldseek_results_path, f'{struct_basename}_output_foldseek', f'{struct_basename}_vs_DB_human_reference_foldseek_results.tsv')
            
            if os.path.exists(result_file) and os.path.getsize(result_file) > 0:
                print(f'  ✓ Foldseek search completed')
                success_count += 1
                foldseek_results_mapping[locus_tag] = [result_file]
            else:
                print(f'  ✗ Foldseek search failed: output file not found or empty')
                logging.error(f'Foldseek output file missing or empty: {result_file}')
                error_count += 1
                foldseek_results_mapping[locus_tag] = []

        except Exception as e:
            print(f'  ✗ Foldseek search failed')
            logging.exception(f'Error running Foldseek search: {e}')
            error_count += 1
            foldseek_results_mapping[locus_tag] = []
    
    print(f'\n{"="*80}')
    print('FOLDSEEK SUMMARY')
    print(f'{"="*80}')
    print(f'Total locus_tags with structures: {len(reference_dict)}')
    print(f'Successfully processed: {success_count}')
    print(f'Errors: {error_count}')
    print(f'{"="*80}\n')

    return foldseek_results_mapping

def run_foldseek_human_colabfold_structures(databases_path, output_path, organism_name, container_engine='docker'):

    """
    Runs Foldseek easy-search against unified human reference structures database
    using ColabFold structures (CB_*.pdb) for each locus_tag.

    Raw Foldseek results are stored in the shared 'foldseek_results' folder so
    existing CB_* queries can be reused if they were already generated by the
    default analysis.

    :param output_path: Directory of the organism output.
    :param databases_path: Directory where FOLDSEEK structure databases are stored.
    :param organism_name: Name of the organism.
    :param container_engine: Container engine to use ('docker' or 'singularity').
    :return: Dictionary with locus_tag as key and path to foldseek results file as value.
    """
    foldseek_results_mapping = {}

    print(f'\n{"="*80}')
    print('FOLDSEEK HUMAN OFFTARGET ANALYSIS (COLABFOLD)')
    print(f'{"="*80}\n')

    db_human_path = os.path.join(databases_path, 'human_structures', 'DB_foldseek')
    organism_structures_path = os.path.join(output_path, organism_name, 'structures')
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)

    offtarget_path = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtarget_path, 'foldseek_results')

    if not os.path.exists(foldseek_results_path):
        os.makedirs(foldseek_results_path, exist_ok=True)

    success_count = 0
    error_count = 0
    skipped_count = 0

    for locus_tag in all_locus_tags:
        locus_dir = os.path.join(organism_structures_path, locus_tag)
        cb_structures = structures.find_colabfold_for_locus(locus_dir)

        if not cb_structures:
            print(f'\n[{locus_tag}] No ColabFold structure found, skipping')
            skipped_count += 1
            foldseek_results_mapping[locus_tag] = []
            continue

        struct_path = cb_structures[0]
        struct_name = os.path.basename(struct_path)
        struct_dir = os.path.dirname(struct_path)

        print(f'\n[{locus_tag}] Processing {struct_name}')

        try:
            programs.run_foldseek_search(
                struct_dir,
                db_human_path,
                'DB_human_reference',
                struct_name,
                foldseek_results_path,
                container_engine=container_engine
            )

            struct_basename = struct_name.split('.')[0]
            result_file = os.path.join(
                foldseek_results_path,
                f'{struct_basename}_output_foldseek',
                f'{struct_basename}_vs_DB_human_reference_foldseek_results.tsv'
            )

            if os.path.exists(result_file) and os.path.getsize(result_file) > 0:
                print('  ✓ Foldseek search completed')
                success_count += 1
                foldseek_results_mapping[locus_tag] = [result_file]
            else:
                print('  ✗ Foldseek search failed: output file not found or empty')
                logging.error(f'Foldseek output file missing or empty: {result_file}')
                error_count += 1
                foldseek_results_mapping[locus_tag] = []

        except Exception as e:
            print('  ✗ Foldseek search failed')
            logging.exception(f'Error running Foldseek search with ColabFold structure: {e}')
            error_count += 1
            foldseek_results_mapping[locus_tag] = []

    print(f'\n{"="*80}')
    print('FOLDSEEK COLABFOLD SUMMARY')
    print(f'{"="*80}')
    print(f'Total locus_tags in genome: {len(all_locus_tags)}')
    print(f'Successfully processed: {success_count}')
    print(f'Skipped (no ColabFold structure): {skipped_count}')
    print(f'Errors: {error_count}')
    print(f'{"="*80}\n')

    return foldseek_results_mapping

def foldseek_human_parser (output_path, organism_name, map_foldseek):

    """
    Parses Foldseek results for reference structures and maps them to locus_tags.
    
    For each locus_tag, selects the best match (highest TM-score) from the unified 
    human reference database search.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param map_foldseek: Dictionary mapping locus_tag to foldseek result file (single file per locus_tag).
    
    :return: Dictionary with locus_tag as key and best foldseek match.
    """

    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtargets_dir, 'foldseek_results')

    foldseek_dict_file = os.path.join(foldseek_results_path, 'human_foldseek_dict.json')

    if not files.file_check(foldseek_dict_file):
        
        print('\nParsing Foldseek results...')
        results_foldseek_dict = {}
        
        # Guard against empty mapping (no structures found)
        if not map_foldseek:
            print('No Foldseek results to parse (empty mapping)')
            with open(foldseek_dict_file, 'w') as f:
                json.dump({}, f)
            return {}
        
        # Parse results for each locus_tag
        for locus_tag, result_files in map_foldseek.items():
            
            # Skip if no result files (e.g., foldseek search failed)
            if not result_files:
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }
                print(f'  {locus_tag}: Foldseek search failed, no results')
                continue
            
            # Process the single result file for this locus_tag
            result_file = result_files[0]
            
            if not files.file_check(result_file):
                print(f'  {locus_tag}: Result file not found: {result_file}')
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }
                continue
            
            try:
                df = pd.read_csv(result_file, sep='\t', usecols=['query', 'target', 'alnlen', 'qcov', 'tcov', 'lddt', 'qtmscore', 'ttmscore', 'alntmscore', 'rmsd', 'prob', 'pident', 'evalue'])
                
                if not df.empty:
                    # Sort by TM score (max of query and target TM-scores)
                    df['max_tmscore'] = df[['qtmscore', 'ttmscore']].max(axis=1)
                    best_row = df.sort_values(by='max_tmscore', ascending=False).iloc[0]
                    
                    results_foldseek_dict[locus_tag] = {
                        'query_structure': best_row['query'],
                        'target_foldseek': best_row['target'],
                        'alnlen_foldseek': best_row['alnlen'],
                        'qcov_foldseek': best_row['qcov'],
                        'tcov_foldseek': best_row['tcov'],
                        'lddt_foldseek': best_row['lddt'],
                        'qtmscore_foldseek': best_row['qtmscore'],
                        'ttmscore_foldseek': best_row['ttmscore'],
                        'alntmscore_foldseek': best_row['alntmscore'],
                        'rmsd_foldseek': best_row['rmsd'],
                        'prob_foldseek': best_row['prob'],
                        'pident_foldseek': best_row['pident'],
                        'evalue_foldseek': best_row['evalue']
                    }
                    print(f'  {locus_tag}: Best match = {best_row["target"]} (TM-score={best_row["max_tmscore"]:.3f})')
                else:
                    # Empty result file
                    results_foldseek_dict[locus_tag] = {
                        'query_structure': None,
                        'target_foldseek': None,
                        'alnlen_foldseek': None,
                        'qcov_foldseek': None,
                        'tcov_foldseek': None,
                        'lddt_foldseek': None,
                        'qtmscore_foldseek': None,
                        'ttmscore_foldseek': None,
                        'alntmscore_foldseek': None,
                        'rmsd_foldseek': None,
                        'prob_foldseek': None,
                        'pident_foldseek': None,
                        'evalue_foldseek': None
                    }
                    print(f'  {locus_tag}: No hits found in foldseek results')
                    
            except Exception as e:
                logging.exception(f'Could not read {result_file}: {e}')
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }
        
        # Save results
        files.dict_to_json(foldseek_results_path, 'human_foldseek_dict.json', results_foldseek_dict)
        print(f'\nFoldseek results saved to {foldseek_dict_file}')
        print(f'Total locus_tags with matches: {len([v for v in results_foldseek_dict.values() if v["target_foldseek"] is not None])}')
    else:
        print(f'Loading existing foldseek results from {foldseek_dict_file}')
        results_foldseek_dict = files.json_to_dict(foldseek_dict_file)
    
    return results_foldseek_dict

def foldseek_human_colabfold_parser(output_path, organism_name, map_foldseek):

    """
    Parses Foldseek results for ColabFold structures and maps them to locus_tags.

    For each locus_tag, selects the best match (highest TM-score) from the unified
    human reference database search using the ColabFold structure as query.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param map_foldseek: Dictionary mapping locus_tag to foldseek result file.

    :return: Dictionary with locus_tag as key and best foldseek match.
    """

    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtargets_dir, 'foldseek_results')

    foldseek_dict_file = os.path.join(foldseek_results_path, 'human_foldseek_colabfold_dict.json')

    if not files.file_check(foldseek_dict_file):

        print('\nParsing Foldseek ColabFold results...')
        results_foldseek_dict = {}

        if not map_foldseek:
            print('No Foldseek ColabFold results to parse (empty mapping)')
            with open(foldseek_dict_file, 'w') as f:
                json.dump({}, f)
            return {}

        for locus_tag, result_files in map_foldseek.items():

            if not result_files:
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }
                print(f'  {locus_tag}: Foldseek ColabFold search failed, no results')
                continue

            result_file = result_files[0]

            if not files.file_check(result_file):
                print(f'  {locus_tag}: Result file not found: {result_file}')
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }
                continue

            try:
                df = pd.read_csv(result_file, sep='\t', usecols=['query', 'target', 'alnlen', 'qcov', 'tcov', 'lddt', 'qtmscore', 'ttmscore', 'alntmscore', 'rmsd', 'prob', 'pident', 'evalue'])

                if not df.empty:
                    df['max_tmscore'] = df[['qtmscore', 'ttmscore']].max(axis=1)
                    best_row = df.sort_values(by='max_tmscore', ascending=False).iloc[0]

                    results_foldseek_dict[locus_tag] = {
                        'query_structure': best_row['query'],
                        'target_foldseek': best_row['target'],
                        'alnlen_foldseek': best_row['alnlen'],
                        'qcov_foldseek': best_row['qcov'],
                        'tcov_foldseek': best_row['tcov'],
                        'lddt_foldseek': best_row['lddt'],
                        'qtmscore_foldseek': best_row['qtmscore'],
                        'ttmscore_foldseek': best_row['ttmscore'],
                        'alntmscore_foldseek': best_row['alntmscore'],
                        'rmsd_foldseek': best_row['rmsd'],
                        'prob_foldseek': best_row['prob'],
                        'pident_foldseek': best_row['pident'],
                        'evalue_foldseek': best_row['evalue']
                    }
                    print(f'  {locus_tag}: Best ColabFold match = {best_row["target"]} (TM-score={best_row["max_tmscore"]:.3f})')
                else:
                    results_foldseek_dict[locus_tag] = {
                        'query_structure': None,
                        'target_foldseek': None,
                        'alnlen_foldseek': None,
                        'qcov_foldseek': None,
                        'tcov_foldseek': None,
                        'lddt_foldseek': None,
                        'qtmscore_foldseek': None,
                        'ttmscore_foldseek': None,
                        'alntmscore_foldseek': None,
                        'rmsd_foldseek': None,
                        'prob_foldseek': None,
                        'pident_foldseek': None,
                        'evalue_foldseek': None
                    }
                    print(f'  {locus_tag}: No hits found in Foldseek ColabFold results')

            except Exception as e:
                logging.exception(f'Could not read {result_file}: {e}')
                results_foldseek_dict[locus_tag] = {
                    'query_structure': None,
                    'target_foldseek': None,
                    'alnlen_foldseek': None,
                    'qcov_foldseek': None,
                    'tcov_foldseek': None,
                    'lddt_foldseek': None,
                    'qtmscore_foldseek': None,
                    'ttmscore_foldseek': None,
                    'alntmscore_foldseek': None,
                    'rmsd_foldseek': None,
                    'prob_foldseek': None,
                    'pident_foldseek': None,
                    'evalue_foldseek': None
                }

        files.dict_to_json(foldseek_results_path, 'human_foldseek_colabfold_dict.json', results_foldseek_dict)
        print(f'\nFoldseek ColabFold results saved to {foldseek_dict_file}')
        print(f'Total locus_tags with ColabFold matches: {len([v for v in results_foldseek_dict.values() if v["target_foldseek"] is not None])}')
    else:
        print(f'Loading existing Foldseek ColabFold results from {foldseek_dict_file}')
        results_foldseek_dict = files.json_to_dict(foldseek_dict_file)

    return results_foldseek_dict

def merge_foldseek_data (output_path, organism_name):
    """
    Format foldseek results for final output table.
    
    With the new structure organization, foldseek results are already keyed by locus_tag,
    so this function primarily reformats the data for the final table.
    
    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param id_equivalences: Dictionary with locus_tag and uniprot_id (for compatibility).
    :param uniprot_proteome_annotations: Dictionary with annotations (for compatibility).

    :return: Dictionary with the merged data formatted for final table.
    """

    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtargets_dir, 'foldseek_results')
    foldseek_res_file = os.path.join(foldseek_results_path, 'human_foldseek_dict.json')
    foldseek_mapped_file = os.path.join(offtargets_dir, f'{organism_name}_final_foldseek_results.json')

    if not files.file_check(foldseek_mapped_file):
        if files.file_check(foldseek_res_file):  

            results_foldseek_dict = files.json_to_dict(foldseek_res_file)

            mapped_dict = {}

            # Results are already organized by locus_tag, just reformat
            for locus_tag, foldseek_data in results_foldseek_dict.items():
                mapped_dict[locus_tag] = {
                    'gene': locus_tag,
                    'query_structure': foldseek_data.get('query_structure'),
                    'structure': foldseek_data.get('query_structure'),  # The reference structure used
                    'target': foldseek_data.get('target_foldseek'),
                    'alnlen': foldseek_data.get('alnlen_foldseek'),
                    'qcov': foldseek_data.get('qcov_foldseek'),
                    'tcov': foldseek_data.get('tcov_foldseek'),
                    'lddt': foldseek_data.get('lddt_foldseek'),
                    'qtmscore': foldseek_data.get('qtmscore_foldseek'),
                    'ttmscore': foldseek_data.get('ttmscore_foldseek'),
                    'alntmscore': foldseek_data.get('alntmscore_foldseek'),
                    'rmsd': foldseek_data.get('rmsd_foldseek'),
                    'prob': foldseek_data.get('prob_foldseek'),
                    'pident': foldseek_data.get('pident_foldseek'),
                    'evalue': foldseek_data.get('evalue_foldseek')
                }

            files.dict_to_json(offtargets_dir, f'{organism_name}_final_foldseek_results.json', mapped_dict)
            print(f'\nFoldseek data merged and saved to {foldseek_mapped_file}')
            print(f'Total genes with foldseek results: {len([v for v in mapped_dict.values() if v["target"] is not None])}')
        else:
            print(f'File {foldseek_res_file} not found.')
            mapped_dict = {}
    else:
        mapped_dict = files.json_to_dict(foldseek_mapped_file)
        print(f'Foldseek results in {foldseek_mapped_file}.')

    return mapped_dict

def merge_foldseek_colabfold_data(output_path, organism_name):
    """
    Format Foldseek ColabFold results for final output table.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.

    :return: Dictionary with the merged data formatted for the final table.
    """

    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')
    foldseek_results_path = os.path.join(offtargets_dir, 'foldseek_results')
    foldseek_res_file = os.path.join(foldseek_results_path, 'human_foldseek_colabfold_dict.json')
    foldseek_mapped_file = os.path.join(offtargets_dir, f'{organism_name}_final_foldseek_colabfold_results.json')

    if not files.file_check(foldseek_mapped_file):
        if files.file_check(foldseek_res_file):

            results_foldseek_dict = files.json_to_dict(foldseek_res_file)

            mapped_dict = {}

            for locus_tag, foldseek_data in results_foldseek_dict.items():
                mapped_dict[locus_tag] = {
                    'gene': locus_tag,
                    'query_structure': foldseek_data.get('query_structure'),
                    'structure': foldseek_data.get('query_structure'),
                    'target': foldseek_data.get('target_foldseek'),
                    'alnlen': foldseek_data.get('alnlen_foldseek'),
                    'qcov': foldseek_data.get('qcov_foldseek'),
                    'tcov': foldseek_data.get('tcov_foldseek'),
                    'lddt': foldseek_data.get('lddt_foldseek'),
                    'qtmscore': foldseek_data.get('qtmscore_foldseek'),
                    'ttmscore': foldseek_data.get('ttmscore_foldseek'),
                    'alntmscore': foldseek_data.get('alntmscore_foldseek'),
                    'rmsd': foldseek_data.get('rmsd_foldseek'),
                    'prob': foldseek_data.get('prob_foldseek'),
                    'pident': foldseek_data.get('pident_foldseek'),
                    'evalue': foldseek_data.get('evalue_foldseek')
                }

            files.dict_to_json(offtargets_dir, f'{organism_name}_final_foldseek_colabfold_results.json', mapped_dict)
            print(f'\nFoldseek ColabFold data merged and saved to {foldseek_mapped_file}')
            print(f'Total genes with Foldseek ColabFold results: {len([v for v in mapped_dict.values() if v["target"] is not None])}')
        else:
            print(f'File {foldseek_res_file} not found.')
            mapped_dict = {}
    else:
        mapped_dict = files.json_to_dict(foldseek_mapped_file)
        print(f'Foldseek ColabFold results in {foldseek_mapped_file}.')

    return mapped_dict

def final_foldseek_structure_table (output_path, organism_name, mapped_dict):
    """
    Create a final table with the merge dictionary of the Foldseek results. 
    Saves the table in a .tsv file named using the organism name followed by '_final_foldseek_results.tsv'in the 'structures' directory.
    Returns a DataFrame with the final results.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param mapped_dict: Dictionary with the merged data.

    :return: DataFrame with the final results.
    """
    
    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')

    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)
    
    # Create a DataFrame with final results
    final_foldseek_file = os.path.join(offtargets_dir, f'{organism_name}_final_foldseek_results.tsv')

    if not files.file_check(final_foldseek_file):

        rows = []

        for locus_tag in all_locus_tags:
            if locus_tag in mapped_dict:
                rows.append(mapped_dict[locus_tag])
            else:
                rows.append({'gene': locus_tag, 'query_structure': None, 'structure': 'No hit', 'target': None, 'alnlen': None, 'qcov': None, 'tcov': None, 'lddt': None, 'qtmscore': None, 'ttmscore': None, 'alntmscore': None, 'rmsd': None, 'prob': None, 'pident': None, 'evalue': None })

        final_foldseek_df = pd.DataFrame(rows).rename(columns={
            'query_structure': 'FS_query_structure',
            'structure': 'FS_organism_structure_query',
            'target': 'FS_human_structure_hit',
            'alnlen': 'FS_alnlen',
            'qcov': 'FS_qcov',
            'tcov': 'FS_tcov',
            'lddt': 'FS_lddt',
            'qtmscore': 'FS_qtmscore',
            'ttmscore': 'FS_ttmscore',
            'alntmscore': 'FS_alntmscore',
            'rmsd': 'FS_rmsd',
            'prob': 'FS_prob',
            'pident': 'FS_pident',
            'evalue': 'FS_evalue'
        })

        final_foldseek_df.to_csv(final_foldseek_file, sep='\t', index=False)
   
        print(f'Foldseek final results saved to {final_foldseek_file}.')
    
    else:
        print(f'Foldseek final results in {final_foldseek_file}.')
        final_foldseek_df = pd.read_csv(final_foldseek_file, sep='\t')

    return final_foldseek_df

def final_foldseek_colabfold_structure_table(output_path, organism_name, mapped_dict):
    """
    Create a final table with the merged dictionary of the Foldseek ColabFold results.
    Saves the table in a .tsv file named using the organism name followed by
    '_final_foldseek_colabfold_results.tsv'.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param mapped_dict: Dictionary with the merged data.

    :return: DataFrame with the final results.
    """

    offtargets_dir = os.path.join(output_path, organism_name, 'offtarget')
    all_locus_tags = metadata.ref_gbk_locus(output_path, organism_name)
    final_foldseek_file = os.path.join(offtargets_dir, f'{organism_name}_final_foldseek_colabfold_results.tsv')

    if not files.file_check(final_foldseek_file):

        rows = []

        for locus_tag in all_locus_tags:
            if locus_tag in mapped_dict:
                rows.append(mapped_dict[locus_tag])
            else:
                rows.append({'gene': locus_tag, 'query_structure': None, 'structure': 'No hit', 'target': None, 'alnlen': None, 'qcov': None, 'tcov': None, 'lddt': None, 'qtmscore': None, 'ttmscore': None, 'alntmscore': None, 'rmsd': None, 'prob': None, 'pident': None, 'evalue': None})

        final_foldseek_df = pd.DataFrame(rows).rename(columns={
            'query_structure': 'FS_CB_query_structure',
            'structure': 'FS_CB_organism_structure_query',
            'target': 'FS_CB_human_structure_hit',
            'alnlen': 'FS_CB_alnlen',
            'qcov': 'FS_CB_qcov',
            'tcov': 'FS_CB_tcov',
            'lddt': 'FS_CB_lddt',
            'qtmscore': 'FS_CB_qtmscore',
            'ttmscore': 'FS_CB_ttmscore',
            'alntmscore': 'FS_CB_alntmscore',
            'rmsd': 'FS_CB_rmsd',
            'prob': 'FS_CB_prob',
            'pident': 'FS_CB_pident',
            'evalue': 'FS_CB_evalue'
        })

        final_foldseek_df.to_csv(final_foldseek_file, sep='\t', index=False)

        print(f'Foldseek ColabFold final results saved to {final_foldseek_file}.')

    else:
        print(f'Foldseek ColabFold final results in {final_foldseek_file}.')
        final_foldseek_df = pd.read_csv(final_foldseek_file, sep='\t')

    return final_foldseek_df

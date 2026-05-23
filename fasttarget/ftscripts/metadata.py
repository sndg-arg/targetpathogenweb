from Bio import SeqIO
import pandas as pd
import os
from ftscripts import files

def ref_gbk_locus(output_path, organism_name):
    """
    Returns a list of locus_tags from the reference genome.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.

    :return: List of locus_tags.
    """
    ref_gbk = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.gbk')

    locus_tags = []

    for record in SeqIO.parse(ref_gbk, "genbank"):
        for feature in record.features:
            if feature.type == "CDS":
                if 'translation' in feature.qualifiers and 'locus_tag' in feature.qualifiers:
                    locus_tags.append(feature.qualifiers["locus_tag"][0])
    
    return locus_tags


def ref_gbk_locus_info(output_path, organism_name):
    """
    Returns a dictionary mapping locus_tags to gene names and products from the reference genome.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.

    :return: Dictionary with locus_tag as key and dict with 'gene_name' and 'product' as values.
    """
    ref_gbk = os.path.join(output_path, organism_name, 'genome', f'{organism_name}.gbk')
    
    locus_info = {}
    
    for record in SeqIO.parse(ref_gbk, "genbank"):
        for feature in record.features:
            if feature.type == "CDS":
                if 'translation' in feature.qualifiers and 'locus_tag' in feature.qualifiers:
                    locus_tag = feature.qualifiers["locus_tag"][0]
                    
                    # Extract gene name (if available)
                    gene_name = ""
                    if 'gene' in feature.qualifiers:
                        gene_name = feature.qualifiers['gene'][0]
                    
                    # Extract product
                    product = ""
                    if 'product' in feature.qualifiers:
                        product = feature.qualifiers['product'][0]
                    
                    locus_info[locus_tag] = {
                        'gene_name': gene_name,
                        'product': product
                    }
    
    return locus_info


def add_gene_product_info(df, output_path, organism_name):
    """
    Add gene_name and product columns to a dataframe that has a 'gene' column.
    This function extracts gene names and product descriptions from the GenBank file
    and adds them as new columns (always positions 2 and 3) after 'gene'.
    
    Column order will always be: gene | gene_name | product | [rest of columns]
    
    If gene_name or product are not found, they will be empty strings.
    
    :param df: DataFrame with a 'gene' column (locus_tag)
    :param output_path: Path to the output directory
    :param organism_name: Name of the organism
    :return: DataFrame with added 'gene_name' and 'product' columns in positions 2 and 3
    """
    
    if 'gene' not in df.columns:
        # If no 'gene' column, return as is
        return df
    
    # Get gene and product info from GenBank
    gbk_info = ref_gbk_locus_info(output_path, organism_name)
    
    # Create new columns with info for each gene
    gene_names = []
    products = []
    
    for gene in df['gene']:
        info = gbk_info.get(gene, {})
        gene_names.append(info.get('gene_name', ''))
        products.append(info.get('product', ''))
    
    # Add columns
    df['gene_name'] = gene_names
    df['product'] = products
    
    # Reorder columns: gene, gene_name, product, [rest]
    cols = df.columns.tolist()
    cols.remove('gene_name')
    cols.remove('product')
    
    # Insert gene_name and product right after 'gene'
    gene_idx = cols.index('gene')
    cols.insert(gene_idx + 1, 'gene_name')
    cols.insert(gene_idx + 2, 'product')
    
    df = df[cols]
    
    return df

def metadata_table_bool(output_path, organism_name, locus_tag_true:str, property:str, out_dir:str):
    """
    Makes a metadata table. Each locus_tag has a boolean value for a property.    

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param locus_tag_true: List of locus_tag TRUE for a property.
    :param property: Name of the property.
    :param out_dir : Output directory path.

    :return: Metadata table. Each locus_tag has TRUE/FALSE value for a property.
    """

    locus_tags = ref_gbk_locus(output_path, organism_name)

    data = {
        "gene": locus_tags,
        property: [locus_tag in locus_tag_true for locus_tag in locus_tags]
    }
    
    metadata_table = pd.DataFrame(data)
    metadata_table.to_csv(f"{out_dir}/{property}.csv", index=False)
    metadata_table.to_csv(f"{out_dir}/{property}.tsv", index=False, sep='\t')

    print(f"{out_dir}/{property}.csv and .tsv have been created.")

    return metadata_table

def metadata_table_with_values(output_path, organism_name, values_dict:str, property:str, out_dir:str, neg_value=None):
    """
    Makes a metadata table. Each locus_tag has a numerical or categorical value for a property.

    :param output_path: Directory of the organism output.
    :param organism_name: Name of the organism.
    :param values_dict: Dictionary with locus_tag and value.
    :param property: Name of the property.
    :param neg_value: The value assigned to the `locus_tag` if it lacks the specified property. Defaults to None.
    :param out_dir : Output directory path.

    :return: Metadata table. Each locus_tag has a numerical or categorical value for a property.
    """

    locus_tags = ref_gbk_locus(output_path, organism_name)

    data = {"gene": [], property: []}
    for locus_tag in locus_tags:
        if locus_tag in values_dict.keys():
            data["gene"].append(locus_tag)
            data[property].append(values_dict[locus_tag])
        else:
            data["gene"].append(locus_tag)
            data[property].append(neg_value)            
    
    metadata_table = pd.DataFrame(data)
    metadata_table.to_csv(f"{out_dir}/{property}.csv", index=False)
    metadata_table.to_csv(f"{out_dir}/{property}.tsv", index=False, sep='\t')

    print(f"{out_dir}/{property}.csv and .tsv have been created.")

    return metadata_table

def tables_for_TP(organism_name, results_path):
    """
    Generates separate metadata tables for each property in the results table.
    This tables can be imported as metadata in Target Pathogen.
    They are saved in the 'tables_for_TP' directory.

    :param organism_name: Name of the organism
    :param results_path: Path to the results directory.
    """

    TP_metadata_path = os.path.join(results_path, 'tables_for_TP')

    results_table_path = os.path.join(results_path, f'{organism_name}_results_table.tsv')

    os.makedirs(TP_metadata_path, exist_ok=True)
    print(f"{TP_metadata_path} has been created.")

    if files.file_check(results_table_path):
        
        results_table = pd.read_csv(results_table_path, sep='\t', header=0)

        # Generate separate metadata tables for each property

        for column in results_table.columns[1:]:
            sub_table = results_table[['gene', column]]
            sub_table.to_csv(f"{TP_metadata_path}/{column}.tsv", index=False, sep='\t')
            print(f"{TP_metadata_path}/{column}.tsv has been created.")
    
    else:
        print(f"{results_table_path} not found.")



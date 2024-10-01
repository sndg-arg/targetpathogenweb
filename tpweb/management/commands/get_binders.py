import os
import re
import pandas as pd
import subprocess as sp
from bioseq.models.Biodatabase import Biodatabase
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
import gzip
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from pdbecif.mmcif_io import CifFileReader
import time

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('--tpwebdir', default="./")

    def handle(self, *args, **options):
        def create_biolip_dataframe(tpwebdir):
            try:
                with gzip.open(os.path.join(tpwebdir, 'biolip', 'BioLiP.txt.gz'), 'rt') as biolip_file:
                    data = [line.strip().split('\t') for line in biolip_file]

                custom_headers = ['PDB ID', 'Receptor chain', 'Resolution', 'Binding site number code', 'Ligand ID', 'Ligand chain', 'Ligand serial numbera', 'Binding site residues (with PDB residue numbering)', 'Binding site residues (with residue re-numbered starting from 1)', 'Catalytic site residues (with PDB residue numbering)', 'Catalytic site residues (with residue re-numbered starting from 1)', 'EC number', 'GO terms', 'Binding affinity by manual survey of the original literature', 'Binding affinity provided by the Binding MOAD database', 'Binding affinity provided by the PDBbind-CN database.', 'Binding affinity provided by the BindingDB database', 'Uniprot', 'PubMed ID', 'Residue sequence number of the ligand', 'Receptor sequence']
                df = pd.DataFrame(data, columns=custom_headers)
                return df

            except FileNotFoundError:
                print(f"The file {os.path.join(tpwebdir, 'biolip', 'BioLiP.txt.gz')} was not found.")
                return None
            except Exception as e:
                print(f"An error occurred: {str(e)}")
                return None

        def download_databases(tpwebdir):
            if not os.path.exists(f'{tpwebdir}/biolip'):
                print('Biolip folder does not exist, creating one...')
                os.makedirs(f'{tpwebdir}/biolip')
                url = "https://zhanggroup.org/BioLiP/download/BioLiP.txt.gz"
                output_filename = f"{tpwebdir}/biolip/BioLiP.txt.gz"
                curl_command = ["curl", "-L", "-o", output_filename, url]

                try:
                    print('Downloading Biolip...')
                    result = sp.run(curl_command, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"File '{output_filename}' has been successfully downloaded.")
                    else:
                        print(f"Failed to download the file. Return code: {result.returncode}")
                        print(f"Error message: {result.stderr}")
                except Exception as e:
                    print(f"An error occurred while trying to download the file: {str(e)}")

                url = "https://files.wwpdb.org/pub/pdb/data/monomers/components.cif"
                output_filename = f"{tpwebdir}/biolip/components.cif"
                curl_command = ["curl", "-L", "-o", output_filename, url]

                try:
                    print('Downloading Chemical Component Dictionary...')
                    result = sp.run(curl_command, capture_output=True, text=True)
                    if result.returncode == 0:
                        print(f"File '{output_filename}' has been successfully downloaded.")
                    else:
                        print(f"Failed to download the file. Return code: {result.returncode}")
                        print(f"Error message: {result.stderr}")
                except Exception as e:
                    print(f"An error occurred while trying to download the file: {str(e)}")

        def create_locustag_dataframe(tpwebdir, folder_path):
            try:
                with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as locus_tag:
                    data = [line.strip().split(' ') for line in locus_tag]
                custom_headers = ['Uniprot', 'Locustag']
                df = pd.DataFrame(data, columns=custom_headers)
                df = df.merge(biolip, how='left', on='Uniprot')
                df = df.dropna(subset=['Ligand ID'])
                df = df.drop_duplicates(subset=['Ligand ID'])
                df = delete_ubiquious(df)
                df = df[['Uniprot', 'Locustag', 'PDB ID', 'Ligand ID']]
                return df

            except FileNotFoundError:
                print(f"The file {os.path.join(folder_path, genome + '_unips.lst')} was not found.")
                return None
            except Exception as e:
                print(f"An error occurred: {str(e)}")
                return None

        def delete_ubiquious(df):
            ubiquious = ['ZN', 'ATP', 'LEU', 'CA', 'PO4', 'MN', 'peptide', 'dna', 'MG', 'FE', 'FE2','HG']
            for compound in ubiquious:
                df = df[df['Ligand ID'] != compound]
            return df

        def get_binders(df):
            data = CifFileReader().read(ccd_cif)
            cif_data = list(data.values())
            smiles_df = pd.DataFrame(columns=['Ligand ID', 'Name', 'Smiles'])
            ligands = set(df['Ligand ID'].tolist())
            for ligand in ligands:
                for comp in cif_data:
                    general_info = comp['_chem_comp']
                    if ligand == general_info['id']:
                        smiles = comp['_pdbx_chem_comp_descriptor']
                        canonical_smiles_index = smiles['program'].index('OpenEye OEToolkits')
                        smiles_df.loc[len(smiles_df)] = [general_info['id'], general_info['name'], smiles['descriptor'][canonical_smiles_index]]
            df = df.merge(smiles_df, how='left', on='Ligand ID')
            return df


        tpwebdir = options['tpwebdir']
        genome = options['genome']
        ss = SeqStore('./data')
        folder_path = ss.db_dir(genome)
        start_time = time.time()
        ccd_cif = os.path.abspath(f"{tpwebdir}/biolip/components.cif")

        download_databases(tpwebdir)
        biolip = create_biolip_dataframe(tpwebdir)
        locustag = create_locustag_dataframe(tpwebdir, folder_path)
        binders = get_binders(locustag)   
        binders.to_csv(f'{folder_path}/binders.csv', index=False)
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"Execution time: {execution_time:.2f} seconds")




    

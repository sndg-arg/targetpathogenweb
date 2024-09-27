import os
import pandas as pd
import subprocess as sp
from bioseq.models.Biodatabase import Biodatabase
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
import gzip


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('tpwebdir')

    def handle(self, *args, **options):

        def create_biolip_dataframe(tpwebdir):
            try:
                with gzip.open(os.path.join(tpwebdir, 'biolip', 'BioLiP.txt.gz'), 'rt') as biolip_file:
                    data = [line.strip().split('\t') for line in biolip_file]

                custom_headers = ['PDB ID', 'Receptor chain', 'Resolution', 'Binding site number code', 'Ligand ID', 'Ligand chain', 'Ligand serial numbera', 'Binding site residues (with PDB residue numbering)', 'Binding site residues (with residue re-numbered starting from 1)', 'Catalytic site residues (with PDB residue numbering)', 'Catalytic site residues (with residue re-numbered starting from 1)', 'EC number', 'GO terms', 'Binding affinity by manual survey of the original literature', 'Binding affinity provided by the Binding MOAD database', 'Binding affinity provided by the PDBbind-CN database.', 'Binding affinity provided by the BindingDB database', 'UniProt ID', 'PubMed ID', 'Residue sequence number of the ligand', 'Receptor sequence']
                df = pd.DataFrame(data, columns=custom_headers)
                return df

            except FileNotFoundError:
                print(f"The file {os.path.join(tpwebdir, 'biolip', 'BioLiP.txt.gz')} was not found.")
                return None
            except Exception as e:
                print(f"An error occurred: {str(e)}")
                return None

        def create_locustag_dataframe(tpwebdir):
            try:
                with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as locus_tag:
                    data = [line.strip().split('\t') for line in locus_tag]
                df = pd.DataFrame(data)
                return df

            except FileNotFoundError:
                print(f"The file {os.path.join(folder_path, genome + '_unips.lst')} was not found.")
                return None
            except Exception as e:
                print(f"An error occurred: {str(e)}")
                return None

        tpwebdir = options['tpwebdir']
        genome = options['genome']
        ss = SeqStore('./data')
        folder_path = ss.db_dir(genome)

        if not os.path.exists(f'{tpwebdir}/biolip'):
            print('Biolip folder does not exist, creating one...')
            os.makedirs(f'{tpwebdir}/biolip')
            url = "https://zhanggroup.org/BioLiP/download/BioLiP.txt.gz"
            output_filename = f"{tpwebdir}/biolip/BioLiP.txt.gz"
            curl_command = ["curl", "-L", "-o", output_filename, url]

            try:
                result = sp.run(curl_command, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"File '{output_filename}' has been successfully downloaded.")
                else:
                    print(f"Failed to download the file. Return code: {result.returncode}")
                    print(f"Error message: {result.stderr}")

            except Exception as e:
                print(f"An error occurred while trying to download the file: {str(e)}")

        unip_file = open(os.path.join(folder_path, genome + '_unips.lst'), 'r')
        uniprots = (line.strip().split(' ') for line in unip_file)

        biolip = create_biolip_dataframe(tpwebdir)
        locustag = create_locustag_dataframe(tpwebdir)

        if biolip is not None:
            print(biolip.head())  # Print the first few rows of the DataFrame






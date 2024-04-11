import csv
import ast
import json
from tpweb.models.Ligand import Ligand
from tpweb.models.Ligand import AccessionLigand
import pandas as pd
from django.db import IntegrityError


import os
import shutil
import sys
import traceback
import gzip
import tempfile
import csv
import ast
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom
import subprocess as sp

class Command(BaseCommand):
    help = 'Loads SMILES data into the database'

    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('ligq_folder')
        parser.add_argument('--tmp', default="/tmp/load_pdb")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):

        # Assignation of parameter and directory pointers.
        seqstore = SeqStore(options['datadir'])
        accession = options['accession']
        ligq_folder = options['ligq_folder']
        json_dict = seqstore.ligand_json(accession, ligq_folder)
        ligand_res_folders = seqstore.ligand_res_folders(accession, ligq_folder)

        # Imports the UniprotID:LocusTag dictionary
        with open(json_dict, 'r') as file:
            data = json.load(file)
        data_list = [{'UniprotID': key, 'LocusTag': value} for key, value in data.items()]
        df = pd.DataFrame(data_list)


        for index, row in df.iterrows():
            ligq_protein_folder = os.path.join(ligand_res_folders, row['UniprotID'])
            chembl_comp = os.path.join(ligq_protein_folder, 'chembl_comp.tbl')
            with open(chembl_comp, 'r') as file:
                    lines = file.readlines()
                    if len(lines) >= 2:
                        print(f"Reading file: {chembl_comp}")
                        for line in lines[1:]:
                            columns = line.split()
                            bioentry_instance = Bioentry.objects.get(accession=row['LocusTag'])
                            print(columns[1])
                            ligand_instance = Ligand.objects.get(ligand_from_key=columns[1])
                            
                            AccessionLigand.objects.create(locus_tag=bioentry_instance,origin='Chembl_comp',ligand=ligand_instance)







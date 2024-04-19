import csv
import ast
from tpweb.models.Ligand import Ligand
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
        seqstore = SeqStore(options['datadir'])
        accession = options['accession']
        ligq = options['ligq_folder']
        ligqplus = seqstore.ligand(accession, ligq)
        df = pd.read_csv(ligqplus)

        for index, row in tqdm(df.iterrows(), total=len(df)):
            id_smiles = ast.literal_eval(row['ID_SMILES'])
            for pair in id_smiles:
                try:
                    Ligand.objects.create(ligand_from_key=pair[0], ligand_smiles=pair[1])
                except IntegrityError:
                    pass



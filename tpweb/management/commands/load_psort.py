
import pandas as pd
import os
import shutil
import sys
import traceback
import gzip
import tempfile
import csv
import ast
from tqdm import tqdm
from tpweb.models.ScoreParam import ScoreParam

from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom
import subprocess as sp
from tpweb.models.Ligand import Ligand
from django.db import IntegrityError
from tpweb.models.CelularLocalization import CelularLocalization
from tpweb.models.ScoreParamValue import ScoreParamValue

class Command(BaseCommand):
    help = 'Loads psort results to DB'

    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        seqstore = SeqStore(options['datadir'])
        accession = options['accession']
        psort = seqstore.psort(accession)
        score_param_instance = ScoreParam.objects.get(name='Celular_localization')
        command = f'grep "Fatal error" {psort}'
        # Execute the command and capture its output
        process = sp.Popen(command, stdout=sp.PIPE, shell=True, text=True)
        output, _ = process.communicate()
        if len(output) == 0:
            print('No faltal error detectected')
            # Read the PSORT results file using pandas
            if os.path.exists(psort):
                psort_df = pd.read_csv(psort, sep='\t')  # Specify separator as '\t' for tab-separated values
                for index, row in tqdm(psort_df.iterrows(), total=len(psort_df)):
                    try:
                        bioentry = Bioentry.objects.get(accession=row['SeqID'].split(' ')[0])
                        CelularLocalization.objects.get_or_create(locus_tag=bioentry, localization=row['Localization'])
                        ScoreParamValue.objects.get_or_create(bioentry=bioentry, value=row['Localization'], score_param=score_param_instance)

                    except IntegrityError:
                        pass


            else:
                self.stdout.write(self.style.ERROR(f"PSORT results file {psort} not found."))
        else:
            self.stdout.write(self.style.ERROR(f"Fatal error detected, localization data import aborted"))
            self.stdout.write(self.style.ERROR(output))


from tpweb.models.Binders import Binders
import pandas as pd
from django.db import IntegrityError
import os
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
import subprocess as sp
from django.core.management.base import BaseCommand, CommandError
from tqdm import tqdm

class Command(BaseCommand):
    help = 'Load binder ligands from binders.csv'

    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        ss = SeqStore(options['datadir'])
        genome_folder = ss.db_dir(options['accession'])
        binders_path = os.path.abspath(f'{genome_folder}/binders.csv')
        df = pd.read_csv(binders_path)
        locustags = df['Locustag'].unique()
        bioentrys = Bioentry.objects.filter(accession__in=locustags)

        for index, row in tqdm(df.iterrows(), total=len(df)):
            for bioentry in bioentrys:
                if bioentry.accession == row['Locustag']:
                    Binders.objects.get_or_create(ccd_id=row['Ligand ID'], pdb_id=row['PDB ID'], uniprot=row['Uniprot'], locustag=bioentry, smiles=row['Smiles'])

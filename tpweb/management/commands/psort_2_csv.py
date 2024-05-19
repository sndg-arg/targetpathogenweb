import warnings
from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning
from django.core.management.base import BaseCommand
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.IndexerIO import IndexerIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BiodatabaseQualifierValue import BiodatabaseQualifierValue
from bioseq.models.BioentryQualifierValue import BioentryQualifierValue
from tpweb.models.pdb import ResidueSetProperty, PDB, PDBResidueSet
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.ScoreParam import ScoreParam
import pandas as pd
from django.db import IntegrityError

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)

import os


class Command(BaseCommand):
    help = 'Index genome'

    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('--datadir', default=os.environ.get("BIOSEQDATADIR", "./data"))

    def handle(self, *args, **options):
        accession = options['accession']
        proteins = Bioentry.objects.filter(biodatabase__name=accession + Biodatabase.PROT_POSTFIX)
        protein_ids = proteins.values_list('bioentry_id', flat=True)
        seqstore = SeqStore(options['datadir'])
        psort = seqstore.psort(accession)
        df = pd.read_csv(psort, sep='\t')
        # Modify the SeqID column to only store the first word
        df['SeqID'] = df['SeqID'].apply(lambda x: x.split()[0])
        # Drop the Score column
        df.drop('Score', axis=1, inplace=True)
        
        # Rename columns
        df.rename(columns={'SeqID': 'gene', 'Localization': 'Celular_localization'}, inplace=True)
        
        seqstore = SeqStore(options['datadir'])
        db_dir = seqstore.db_dir(accession)
        csv_filename = 'psort.tsv' 
        csv_path = os.path.join(db_dir,csv_filename)
        df.to_csv(csv_path, sep='\t', index=False)
        print(df)
        #df = pd.DataFrame(columns=['gene', 'Celular_localization'])



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
        pdb = BioentryStructure.objects.filter(bioentry_id__in=protein_ids)
        pdb_ids = pdb.values_list('pdb_id', flat=True)
        rs = PDBResidueSet.objects.filter(pdb_id__in=pdb_ids)
        rs_ids = rs.values_list('id', flat=True)
        rsp = ResidueSetProperty.objects.filter(pdbresidue_set_id__in=rs_ids, property_id=21)
        rsp_ids = rsp.values_list('value', flat=True)
        
        df = pd.DataFrame(columns=['gene', 'rsp_value', 'd_char'])


        index = 0
        # Iterate over each protein

        for protein in tqdm(proteins, total=len(proteins)):
            
            # Get the bioentry_id for the current protein
            bioentry_id = protein.bioentry_id
            bioentry_name = protein.accession
            try:
                pdb_id = BioentryStructure.objects.get(bioentry_id=bioentry_id).pdb_id
            except:
                continue
            rs = PDBResidueSet.objects.filter(pdb_id=pdb_id)
            if rs.exists():
                highest_rsp_value = None
                highest_bioentry_id = None
                highest_d_char = None
                for resset in rs:
                    rsp = ResidueSetProperty.objects.get(pdbresidue_set_id=resset.id, property_id=21)
                    if rsp.value < 0.5:
                        d_char = 'L'
                    elif rsp.value > 0.5 and rsp.value < 0.7:
                        d_char = 'M'
                    else:
                        d_char = 'H'
                    if highest_rsp_value is None or rsp.value > highest_rsp_value:
                        highest_rsp_value = rsp.value
                        highest_bioentry_id = bioentry_name
                        highest_d_char = d_char
                df.loc[index] = [highest_bioentry_id, highest_rsp_value, highest_d_char]
            index += 1
        df.drop_duplicates()

        # Drop the 'rsp_value' column
        df.drop(columns=['rsp_value'], inplace=True)

        # Rename the 'd_char' column to 'druggability'
        df.rename(columns={'d_char': 'druggability'}, inplace=True)
        # After creating and manipulating the DataFrame df

        seqstore = SeqStore(options['datadir'])
        db_dir = seqstore.db_dir(accession)
        csv_filename = 'druggability.tsv' 
        
        csv_path = os.path.join(db_dir,csv_filename)
        df.to_csv(csv_path, sep='\t', index=False)  # Save the DataFrame to a CSV file without including the index column
        print(f'DataFrame saved to {csv_filename}')

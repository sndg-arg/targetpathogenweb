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
        
        df = pd.DataFrame(columns=['bioentry_id', 'rsp_value', 'd_char'])


        index = 0
        # Iterate over each protein

        for protein in tqdm(proteins, total=len(proteins)):
            
            # Get the bioentry_id for the current protein
            bioentry_id = protein.bioentry_id
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
                        d_char = 'Low'
                    elif rsp.value > 0.5 and rsp.value < 0.7:
                        d_char = 'Medium'
                    else:
                        d_char = 'High'
                    if highest_rsp_value is None or rsp.value > highest_rsp_value:
                        highest_rsp_value = rsp.value
                        highest_bioentry_id = bioentry_id
                        highest_d_char = d_char
                df.loc[index] = [highest_bioentry_id, highest_rsp_value, highest_d_char]
            index += 1
        df.drop_duplicates()
        ScoreParam.Initialize2()
        score_param_instance = ScoreParam.objects.get(name='Druggability')

        # Inside your handle method, before the loop that iterates over df rows
        error_rows = []

        for index, row in df.iterrows():
            bioentry_id = Bioentry.objects.get(bioentry_id=row['bioentry_id'])
            try:
                ScoreParamValue.objects.get_or_create(bioentry=bioentry_id, value=row['d_char'], numeric_value=row['rsp_value'], score_param=score_param_instance)
            except IntegrityError as e:
                # Log the error or handle it as needed
                print(f"Error creating ScoreParamValue for row {index}: {e}")
                error_rows.append(index)

        # After the loop, print the list of error-related rows if there are any
        if error_rows:
            print(f"Encountered errors in the following rows: {error_rows}")



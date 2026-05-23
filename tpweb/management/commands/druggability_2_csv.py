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
from tpweb.models.pdb import ResidueSetProperty, PDB, PDBResidueSet, Property
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.structure_sources import classify_structure_experiment, STRUCTURE_SOURCE_EXPERIMENTAL
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
        property_instance = Property.objects.get(name='druggability_score')
        
        df = pd.DataFrame(columns=['gene', 'Druggability'])


        index = 0
        # Iterate over each protein

        for protein in tqdm(proteins, total=len(proteins)):
            
            # Get the bioentry_id for the current protein
            bioentry_id = protein.bioentry_id
            bioentry_name = protein.accession
            structures = list(BioentryStructure.objects.filter(
                bioentry_id=bioentry_id
            ).select_related("pdb"))
            if not structures:
                continue

            experimental_pdb_ids = [
                structure.pdb_id for structure in structures
                if classify_structure_experiment(structure.pdb.experiment) == STRUCTURE_SOURCE_EXPERIMENTAL
            ]
            model_pdb_ids = [
                structure.pdb_id for structure in structures
                if structure.pdb_id not in experimental_pdb_ids
            ]

            # Prefer experimentally determined structures. If none carry FPocket
            # scores, fall back to predicted models (AlphaFold/ColabFold).
            values = self._druggability_values(experimental_pdb_ids, property_instance)
            if not values:
                values = self._druggability_values(model_pdb_ids, property_instance)

            if values:
                df.loc[index] = [bioentry_name, max(values)]
                index += 1
        df.drop_duplicates()

        seqstore = SeqStore(options['datadir'])
        db_dir = seqstore.db_dir(accession)
        csv_filename = 'druggability.tsv' 
        
        os.makedirs(db_dir, exist_ok=True)
        csv_path = os.path.join(db_dir,csv_filename)
        df.to_csv(csv_path, sep='\t', index=False)  # Save the DataFrame to a CSV file without including the index column
        print(f'DataFrame saved to {csv_path} ({len(df)} rows)')

    def _druggability_values(self, pdb_ids, property_instance):
        if not pdb_ids:
            return []
        return list(
            ResidueSetProperty.objects.filter(
                pdbresidue_set__pdb_id__in=pdb_ids,
                pdbresidue_set__residue_set__name="FPocketPocket",
                property=property_instance,
                value__isnull=False,
            ).values_list('value', flat=True)
        )

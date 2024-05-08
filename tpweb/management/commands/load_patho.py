import os
import sys
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from tpweb.models.Pathways import Pathway
from bioseq.models.Bioentry import Bioentry
from bioseq.io.SeqStore import SeqStore
from tqdm import tqdm
from django.db import transaction

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('accession')
        parser.add_argument('--datadir', default="./data")


    def handle(self, *args, **options):
        # Check if a path is provided
        if len(sys.argv) < 2:
            print("Usage: python manage.py load_patho <path_to_directory>")
            sys.exit(1)
        
        # The path provided by the user
        accession = options['accession']
        seqstore = SeqStore(options['datadir'])
        path = seqstore.pwtools_out(accession)
        print(path)
        
        # Construct the full path to the genes.tsv file
        file_path = os.path.join(path, 'genes.tsv')
        
        # Open the file with pandas
        try:
            df = pd.read_csv(file_path, sep='\t')
            # Filter out rows with NaN in the Compounds column
            df = df.dropna(subset=['Compounds'])

            # Iterate over each row in the DataFrame
            with transaction.atomic():
                for index, row in tqdm(df.iterrows(), total=len(df)):
                    compounds = row['Compounds'].split(", ")
                    for compound in compounds:
                        try:
                            bioentry_instance = Bioentry.objects.get(accession__iexact=compound)

                            Pathway.objects.get_or_create(
                                locus_tag=bioentry_instance,
                                pathway=row['Identifier'])
                        except Bioentry.DoesNotExist:
                            print(f"Bioentry with accession {compound} does not exist.")


        except FileNotFoundError:
            print(f"File not found: {file_path}")
            sys.exit(1)
        except pd.errors.EmptyDataError:
            print(f"No data in file: {file_path}")
            sys.exit(1)



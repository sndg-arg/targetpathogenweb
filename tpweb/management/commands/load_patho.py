import os
import sys
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from tpweb.models.Pathways import Pathway
from bioseq.models.Bioentry import Bioentry

class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('datadir')



    def handle(self, *args, **options):
        # Check if a path is provided
        if len(sys.argv) < 2:
            print("Usage: python manage.py load_patho <path_to_directory>")
            sys.exit(1)
        
        # The path provided by the user
        path = options['datadir']
        
        # Construct the full path to the genes.tsv file
        file_path = os.path.join(path, 'genes.tsv')
        
        # Open the file with pandas
        try:
            df = pd.read_csv(file_path, sep='\t')
            # Filter out rows with NaN in the Compounds column
            df = df.dropna(subset=['Compounds'])

            # Print the headers and dimension
            print("Headers:", df.columns.tolist())
            print("Dimensions:", df.shape)

            # Iterate over each row in the DataFrame
            for index, row in df.iterrows():
                compounds = row['Compounds'].split(", ")
                for compound in compounds:
                    try:
                        bioentry_instance = Bioentry.objects.get(accession__iexact=compound)

                        Pathway.objects.get_or_create(
                            locus_tag=bioentry_instance,
                            pathway=row['Identifier'])
                    except Bioentry.DoesNotExist:
                        print(f"Bioentry with accession {compound} does not exist.")



                # Create a new Pathway instance for each row or get it if it already exists
                #pathway_instance, created = Pathway.objects.get_or_create(
                #    pathway=row['Identifier'],
                #    defaults={'locus_tag': Bioentry.objects.get_or_create(accession=row['Compounds'])[0]}
                #)
               # 
               # if created:
               #     self.stdout.write(self.style.SUCCESS(f'Successfully created Pathway: {pathway_instance.pathway}'))
               # else:
               #     self.stdout.write(self.style.WARNING(f'Pathway already exists: {pathway_instance.pathway}'))
                
        except FileNotFoundError:
            print(f"File not found: {file_path}")
            sys.exit(1)
        except pd.errors.EmptyDataError:
            print(f"No data in file: {file_path}")
            sys.exit(1)



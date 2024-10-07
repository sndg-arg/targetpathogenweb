import os
import yaml
import subprocess as sp
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Taxon import Taxon
import pandas as pd

class Command(BaseCommand):
    help = '''Takes genome genkbak indentifier, modify the config.py
              of fasttarget and runs the pipeline.'''

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('folder_path')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        genome = options['genome']
        folder_path = options['folder_path']
        datadir = options['datadir']
        gbk_path = os.path.join(folder_path, f"{genome}.gbk")
        taxon = Taxon.objects.filter(bioentry__identifier=genome)[0]
        name = taxon.scientificName.split()[0]
        taxon_id = taxon.ncbi_taxon_id
        input_filename = "/app/fasttarget/config.yml"
        ss = SeqStore(datadir)
        

        with open(input_filename, 'r') as file:
            config = yaml.safe_load(file)

        if config is None:
            print("Error: Unable to parse the YAML file.")
        else:
            config['organism']['name'] = name
            config['organism']['tax_id'] = taxon_id
            config['organism']['gbk_file'] = gbk_path
        with open(input_filename, 'w') as file:
            yaml.safe_dump(config, file)

        command = "python /app/fasttarget/fasttarget.py"
        results = sp.run(command, shell=True, capture_output=True, text=True)
        print(results.stdout, results.stderr)

        human = pd.read_csv(f'/app/fasttarget/organism/{name}/tables_for_TP/human_offtarget.tsv', sep='\t')
        human['human_offtarget'] = human['human_offtarget'].apply(lambda x: 'hit' if x != 'no_hit' else x)
        human.to_csv(ss.human_offtarget(genome), index=False, sep='\t')
        print(results.stdout, results.stderr)


        micro = pd.read_csv(f'/app/fasttarget/organism/{name}/tables_for_TP/gut_microbiome_offtarget.tsv', sep='\t')
        micro['gut_microbiome_offtarget'] = micro['gut_microbiome_offtarget'].apply(lambda x: 'hit' if x != 'no_hit' else x)
        micro.to_csv(ss.micro_offtarget(genome), index=False, sep='\t')
        print(results.stdout, results.stderr)

        command = f"cp /app/fasttarget/organism/{name}/tables_for_TP/hit_in_deg.tsv {ss.essenciality(genome)}"
        results = sp.run(command, shell=True, capture_output=True, text=True)
        print(results.stdout, results.stderr)

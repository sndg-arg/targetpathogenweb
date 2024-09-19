import os
import yaml
import subprocess as sp
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Taxon import Taxon

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

        command = f"cp /app/fasttarget/organism/{name}/tables_for_TP/human_offtarget.tsv {ss.human_offtarget(genome)}"
        results = sp.run(command, shell=True, capture_output=True, text=True)
        print(results.stdout, results.stderr)

        command = f"cp /app/fasttarget/organism/{name}/tables_for_TP/gut_microbiome_offtarget.tsv {ss.micro_offtarget(genome)}"
        results = sp.run(command, shell=True, capture_output=True, text=True)
        print(results.stdout, results.stderr)

        command = f"cp /app/fasttarget/organism/{name}/tables_for_TP/hit_in_deg.tsv {ss.essenciality(genome)}"
        results = sp.run(command, shell=True, capture_output=True, text=True)
        print(results.stdout, results.stderr)

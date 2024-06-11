import os
import gzip
import argparse
import subprocess as sp
from tqdm import tqdm
import pandas as pd
from SNDG.Structure.FPocket import FpocketOutput
from SNDG import mkdir
import json
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from glob import glob

class Command(BaseCommand):
    help = 'Takes the genome and locus_tag as arguments and retrives the json to be upload with load_fpocket'

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('locus_tag')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")
    
    def handle(self, *args, **options):
        genome = options["genome"]
        locus_tag = options["locus_tag"]
        seqstore = SeqStore(options["datadir"])
        p2rank_output = seqstore.p2rank_pdb_predictions(genome,locus_tag)
        fpocket_folder = seqstore.p2rank_fpocket_folder(genome,locus_tag)

        data_list = []
        df = pd.read_csv(p2rank_output)
        df.columns = [x.strip() for x in df.columns]
        for _, record in tqdm(list(df.iterrows())):
            name = int(record["name"][6:].replace(" ", ""))
            residues = record["residue_ids"].replace("_", "").split()
            atoms = record["surf_atom_ids"].split()
            data_dict = {
                "number": name,
                "residues": residues,
                "atoms": atoms
                        }
            data_list.append(data_dict)
        json_filename = f"p2pocket.json"  # Dynamic filename based on genome and locus_tag
        json_path = os.path.join(seqstore.p2rank_folder(genome, locus_tag) ,json_filename)  # Full path to the JSON file
        with open(json_path, 'w') as outfile:
            json.dump(data_list, outfile)
        with gzip.open(json_path + '.gz', 'wb') as gzoutfile:
            gzoutfile.write(open(json_path, 'rb').read())

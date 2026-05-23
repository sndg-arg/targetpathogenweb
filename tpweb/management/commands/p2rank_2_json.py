import gzip
import json
import os

import pandas as pd
from django.core.management.base import BaseCommand
from tqdm import tqdm

from bioseq.io.SeqStore import SeqStore

class Command(BaseCommand):
    help = 'Takes the genome and locus_tag as arguments and retrives the json to be upload with load_fpocket'

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('locus_tag')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def _write_empty_output(self, seqstore, genome, locus_tag, reason):
        output_dir = seqstore.p2rank_folder(genome, locus_tag)
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, "p2pocket.json")
        with open(json_path, 'w', encoding="utf-8") as outfile:
            json.dump([], outfile)
        with gzip.open(json_path + '.gz', 'wt', encoding="utf-8") as gzoutfile:
            json.dump([], gzoutfile)
        self.stderr.write(
            f"P2Rank output missing or invalid for {genome}/{locus_tag}; wrote empty pocket set ({reason})."
        )
    
    def handle(self, *args, **options):
        genome = options["genome"]
        locus_tag = options["locus_tag"]
        seqstore = SeqStore(options["datadir"])
        p2rank_output = seqstore.p2rank_pdb_predictions(genome, locus_tag)

        data_list = []
        if not os.path.exists(p2rank_output):
            self._write_empty_output(seqstore, genome, locus_tag, "predictions.csv not found")
            return

        try:
            df = pd.read_csv(p2rank_output)
        except (FileNotFoundError, pd.errors.EmptyDataError) as exc:
            self._write_empty_output(seqstore, genome, locus_tag, str(exc))
            return

        df.columns = [x.strip() for x in df.columns]
        for _, record in tqdm(list(df.iterrows())):
            name = int(record["name"][6:].replace(" ", ""))
            residues = record["residue_ids"].replace("_", "").split()
            atoms = record["surf_atom_ids"].split()
            score = record["score"]
            probability = record["probability"]
            properties = {
                "P2Rank score": score,
                "P2Rrank probability": probability
            }
            data_dict = {
                "number": name,
                "residues": residues,
                "atoms": atoms,
                "properties": properties
            }
            data_list.append(data_dict)
        json_path = os.path.join(seqstore.p2rank_folder(genome, locus_tag), "p2pocket.json")
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, 'w', encoding="utf-8") as outfile:
            json.dump(data_list, outfile)
        with gzip.open(json_path + '.gz', 'wt', encoding="utf-8") as gzoutfile:
            json.dump(data_list, gzoutfile)

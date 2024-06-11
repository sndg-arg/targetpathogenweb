import os
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
    help = 'Takes the genome and locus_tag as arguments and retrives the fpocket version of p2rank pockets'

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('locus_tag')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")
    
    def handle(self, *args, **options):
        def replace_first_line(src_filename, target_filename, replacement_line):
            with open(src_filename, 'r') as f:
                first_line, remainder = f.readline(), f.read()
            with open(target_filename, "w") as t:
                t.write(replacement_line + "\n")
                t.write(remainder)

        genome = options["genome"]
        locus_tag = options["locus_tag"]
        seqstore = SeqStore(options["datadir"])
        fpocket_template = "docker run --user $UID:$GID --rm -i -v {workdir}:{workdir} ezequieljsosa/fpocket fpocket -f {pdbinput} -m 2 -D 6"
        p2rank_output = seqstore.p2rank_pdb_predictions(genome,locus_tag)
        pdb = seqstore.structure_af_pdb(genome,locus_tag)
        fpocket_folder = seqstore.p2rank_fpocket_folder(genome,locus_tag)
        if not os.path.exists(fpocket_folder):
            os.makedirs(fpocket_folder)

        df = pd.read_csv(p2rank_output)
        df.columns = [x.strip() for x in df.columns]
        with open(pdb) as h:
            pdb_lines = h.readlines()
        outpockets =[]
        for _, record in tqdm(list(df.iterrows())):

            residues = [x.strip() for x in record.residue_ids.split()]
            atoms = [x.strip() for x in record.surf_atom_ids.split()]
            pocket_name = record["name"].strip()
            pdb_pocket_file = fpocket_folder + "/" + pocket_name + ".pdb"
            with open(pdb_pocket_file, "w") as h:
                for x in pdb_lines:
                    if x.startswith("ATOM"):
                        rid = x.split()[4].strip() + "_" + x.split()[5].strip()
                        if rid in residues:
                            h.write(x)
                    else:
                        h.write(x)

            fpo = FpocketOutput(directory=fpocket_folder + pocket_name + "_out")
            absolute_pocket_path = os.path.abspath(seqstore.p2rank_folder(genome, locus_tag))
            absolute_pdb_input = os.path.abspath(pdb_pocket_file)
            if not os.path.exists(fpo._info_file_path()):
                cmd = fpocket_template.format(pdbinput=absolute_pdb_input, workdir=absolute_pocket_path)
                sp.call(cmd, shell=True)

            # Find all _out folders within the main folder
            _out_folders = sorted(glob(os.path.join(fpocket_folder, 'pocket*_out')))
            print(_out_folders)
            for i, folder in enumerate(_out_folders, start=1):
                # Construct the source and target filenames
                src_filename = os.path.join(folder, f'pocket{i}_info.txt')
                target_filename = os.path.join(fpocket_folder, f'pocket{i}_info_fixed.txt')
                
                # Modify the first line of the source file
                replacement_line = f"Pocket {i} :"
                replace_first_line(src_filename, target_filename, replacement_line)
            # Now, you can proceed with concatenating the fixed files if needed
            # Example: Concatenate all fixed pocketX_info.txt files into a single file
            fixed_files = [os.path.join(fpocket_folder, f'pocket{i}_info_fixed.txt') for i in range(1, len(_out_folders)+1)]
            concatenated_content = ''
            for file in fixed_files:
                with open(file, 'r') as f:
                    content = f.read()
                    concatenated_content += content

            # Define the path for the output file in the main folder
            output_file_path = os.path.join(fpocket_folder, 'all_pockets_info_fixed.txt')

            # Write the concatenated content to the output file
            with open(output_file_path, 'w') as outfile:
                outfile.write(concatenated_content)

            print(f"Concatenation completed. Output saved to {output_file_path}")

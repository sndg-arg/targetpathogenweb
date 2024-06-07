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

class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('locus_tag')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")
    
    def handle(self, *args, **options):
        genome = options["genome"]
        locus_tag = options["locus_tag"]
        seqstore = SeqStore(options["datadir"])
        fpocket_template = "docker run --user $UID:$GID --rm -i -v {workdir}:{workdir} ezequieljsosa/fpocket fpocket -f {pdbinput} -m 2 -D 6"
        p2rank_output = seqstore.p2rank_pdb_predictions(genome,locus_tag)
        pdb = seqstore.structure_af_pdb(genome,locus_tag)
        pocket_tmp = seqstore.p2rank_fpocket_folder(genome,locus_tag)
        print(p2rank_output)
        print(pdb)
        print(pocket_tmp)
        output_path = "/home/eze/workspace/pockets/p2rank_2.4/8IWM/pockets.json"
        if not os.path.exists(pocket_tmp):
            os.makedirs(pocket_tmp)

        df = pd.read_csv(p2rank_output)
        df.columns = [x.strip() for x in df.columns]
        with open(pdb) as h:
            pdb_lines = h.readlines()
        outpockets =[]
        for _, record in tqdm(list(df.iterrows())):

            residues = [x.strip() for x in record.residue_ids.split()]
            atoms = [x.strip() for x in record.surf_atom_ids.split()]
            pocket_name = record["name"].strip()
            pdb_pocket_file = pocket_tmp + "/" + pocket_name + ".pdb"
            with open(pdb_pocket_file, "w") as h:
                for x in pdb_lines:
                    if x.startswith("ATOM"):
                        rid = x.split()[4].strip() + "_" + x.split()[5].strip()
                        if rid in residues:
                            h.write(x)
                    else:
                        h.write(x)

            fpo = FpocketOutput(directory=pocket_tmp + pocket_name + "_out")
            print(fpo._info_file_path())
            absolute_pocket_path = os.path.abspath(seqstore.p2rank_folder(genome, locus_tag))
            absolute_pdb_input = os.path.abspath(pdb_pocket_file)
            print(absolute_pocket_path) 
            if not os.path.exists(fpo._info_file_path()):
                cmd = fpocket_template.format(pdbinput=absolute_pdb_input, workdir=absolute_pocket_path)
                sp.call(cmd, shell=True)
            #sp.call(f"sudo chown -R gabi:gabi {absolute_pocket_path}")

  #          if os.path.exists(fpo._info_file_path()):
  #              fpo.parse()
  #              if fpo.pockets:
  #                  pprops = fpo.pockets[0].properties
  #                  pprops["name"] = pocket_name
  #                  pprops["residues"] = residues
  #                  pprops["atoms"] = atoms
  #                  pprops["score"] = record["score"]
  #                  pprops["probability"] = record["probability"]
  #                  pprops["sas_points"] = record["sas_points"]
  #                  pprops["alpha_spheres"] = fpo.pockets[0].alpha_spheres
  #                  outpockets.append(pprops)
  #      with open(output_path,"w") as h:
  #          json.dump(outpockets,h)

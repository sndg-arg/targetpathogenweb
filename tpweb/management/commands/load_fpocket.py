import os
import shutil
import sys
import traceback
import warnings
import re
import json
from glob import glob
from tqdm import tqdm
from django.core.management.base import BaseCommand, CommandError

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.io.FPocket2SQL import FPocket2SQL
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom, Property, ResidueSet

from django.db import transaction

from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
import json
import gzip


def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):
        parser.add_argument('struct_name')
        parser.add_argument('--P2rank_pocket', action="store_true")
        parser.add_argument('--pocket_json')
        parser.add_argument('--tmp', default="/tmp/load_pdb")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        seqstore = SeqStore(options['datadir'])
        code = options["struct_name"]
        pdb = PDB.objects.filter(code=code)

        if not pdb.exists():
            self.stderr.write(f"Structure {code} does not exists")
            sys.exit(1)
        pdb = pdb.get()

        if not options["pocket_json"]:
            biodbname = pdb.sequences.all()[0].bioentry.biodatabase.name.replace(Biodatabase.PROT_POSTFIX, "")
            seqname = pdb.sequences.all()[0].bioentry.accession
            pocket_json = seqstore.structure_dir(biodbname, seqname) + "/fpocket.json.gz"
        else:
            pocket_json = options["pocket_json"]

        assert os.path.exists(pocket_json), f'"{pocket_json}" does not exists!'

        if options["P2rank_pocket"]:  
            fp2sql = FPocket2SQL()
            fp2sql.create_or_get_pocket_properties(p2rank=True) 
            fp2sql.load_pdb(code, p2rank=True)
            with gzip.open(pocket_json) as h:
                fp2sql.res_pockets = json.load(h)
                print(fp2sql.res_pockets)
            fp2sql.load_pockets(p2rank=True)

            self.stderr.write(f"done loading pockets for: {code} ")
        else:
            fp2sql = FPocket2SQL()
            fp2sql.create_or_get_pocket_properties()
            fp2sql.load_pdb(code)
            with gzip.open(pocket_json) as h:
                fp2sql.res_pockets = json.load(h)
                print(fp2sql.res_pockets)
            fp2sql.load_pockets()

            self.stderr.write(f"done loading pockets for: {code} ")

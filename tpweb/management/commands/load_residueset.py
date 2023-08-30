import os
import shutil
import sys
import traceback
import gzip
import tempfile

import numpy as np
import pandas as pd
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom, ResidueSet, ResidueSetResidue, PDBResidueSet, Property, \
    ResidueProperty, ResidueSetProperty
import subprocess as sp
from django.db import transaction

def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):

        parser.add_argument('struct_name')
        parser.add_argument('residueset_tsv',help="tsv with: feature_type feature_id chain_resids prop1 prop2 ... ")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):

        code = options["struct_name"]
        pdb = PDB.objects.filter(code=code)

        assert os.path.exists(options["residueset_tsv"]), f'"{options["residueset_tsv"]}" does not exists!'

        if not pdb.exists():
            self.stderr.write(f"Structure {code} does not exists")
            sys.exit(1)

        pdb = pdb.get()

        df = pd.read_csv(options["residueset_tsv"],sep="\t",index_col=False)
        assert "feature_id" in df.columns, "feature_id is not in the column list"
        assert "chain_resids" in df.columns, "chain_resids is not in the column list"
        for _,r in df.iterrows():
            with transaction.atomic():
                rs = ResidueSet.objects.get_or_create(name=r.feature_type)[0]
                PDBResidueSet.objects.filter(pdb=pdb,residue_set=rs,name=r.feature_id).delete()
                prs = PDBResidueSet(pdb=pdb,residue_set=rs,name=r.feature_id)
                prs.save()
                residues_dict = {res.chain + "_" + str(res.resid):res for res in pdb.residues.all() }

                residues =  [residues_dict[x] for x in residues_dict if x in r.chain_resids.split(",")]
                for res in residues:
                    ResidueSetResidue( pdbresidue_set=prs,residue=res).save()
                for col in set(df.columns) - set("feature_type feature_id chain_resids".split()):
                    if r[col] and not np.isnan(r[col]):
                        if isinstance(r[col], (int, float, complex)):
                            prop = Property.objects.get_or_create(name=col)[0]
                            ResidueSetProperty(pdbresidue_set=prs,property=prop,value=r[col])

        self.stderr.write(f"done processing: {code} ")


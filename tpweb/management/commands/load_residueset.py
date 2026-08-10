import os
import sys

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction

from tpweb.models.pdb import PDB, ResidueSet, ResidueSetResidue, PDBResidueSet, Property, \
    ResidueSetProperty

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


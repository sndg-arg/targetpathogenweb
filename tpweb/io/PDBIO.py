# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os
import warnings

from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)

from pdbdb.models import PDB
from pdbdb.io.FPocket2SQL import FPocket2SQL
from pdbdb.io.PDB2SQL import PDB2SQL


class PDBIO():

    def __init__(self, pdbs_dir="/data/databases/pdb/divided/",
                 entries_path="/data/databases/pdb/entries.idx",
                 tmp="/tmp/PDBIO"):
        self.pdbs_dir = pdbs_dir
        self.entries_path = entries_path
        self.tmp = tmp

    def init(self):
        self.pdb2sql = PDB2SQL(self.pdbs_dir, self.entries_path)
        self.pdb2sql.load_entries()
        self.fpocket2sql = FPocket2SQL()
        self.fpocket2sql.create_or_get_pocket_properties()


    def pdb_path(self,pdb_code):
        return os.path.sep.join([self.pdbs_dir, pdb_code[1:3], "pdb" + pdb_code + ".ent"])

    def process_pdb(self, pdb_code):
        assert self.pdb2sql, "PDBIO not initialized"
        pdb_code = pdb_code.lower()


        if PDB.objects.filter(code=pdb_code).exists():
            raise Exception("PDB already exists")

        pdb_path = self.pdb_path(pdb_code)
        if not os.path.exists(pdb_path):
            pdb_path = self.pdb2sql.download(pdb_code)

        self.pdb2sql.create_pdb_entry(pdb_code, pdb_path)
        self.pdb2sql.update_entry_data(pdb_code, pdb_path)
        self.fpocket2sql.load_pdb(pdb_code)
        self.fpocket2sql.run_fpocket(self.tmp)
        self.fpocket2sql.load_pockets()
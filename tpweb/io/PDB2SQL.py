import math
import os
import warnings

import pandas as pd
from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning
from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.db import transaction
from tqdm import tqdm

from pdbdb.models import PDB, Residue, Atom

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)

import subprocess as sp



class PDB2SQL():
    def __init__(self, base_dir="/data/databases/pdb/divided/", entries_path="/data/databases/pdb/entries.idx"):
        self.base_dir = base_dir
        self.entries_path = entries_path
        self.entries_df = None

    def load_entries(self):
        assert os.path.exists(self.entries_path), "%s does not exists" % self.entries_path
        entries_columns = ["IDCODE", "HEADER", "ACCESSIONDATE", "COMPOUND", "SOURCE", "AUTHORS", "RESOLUTION",
                           "EXPERIMENT"]
        self.entries_df = pd.read_table(self.entries_path, skiprows=[0, 1, 2], sep='\t', names=entries_columns)

    def download(self, code, overwrite=False):
        code = code.lower()
        pdb_path = self.base_dir + "%s/pdb%s.ent" % (code[1:3], code)

        if overwrite or not os.path.exists(pdb_path):
            pdb_dir_idx = self.base_dir + "%s/" % code[1:3]
            if not os.path.exists(pdb_dir_idx):
                os.mkdir(pdb_dir_idx)

            sp.check_output("wget -O %s.gz ftp://ftp.wwpdb.org/pub/pdb/data/structures/divided/pdb/%s/pdb%s.ent.gz"
                            % (pdb_path, code[1:3], code), shell=True)
            sp.check_output("gunzip %s.gz" % pdb_path, shell=True)
        else:
            print("%s already exists" % pdb_path)
        return pdb_path

    def create_pdb_entry(self, code, pdb_path):
        assert os.path.exists(self.base_dir), "%s does not exists" % self.base_dir
        if PDB.objects.filter(code=code).exists():
            print("%s already exists" % code)
            return PDB.objects.get(code=code)

        try:
            entry = self.entries_df[self.entries_df.IDCODE == code.upper()].iloc[0]
        except IndexError:
            raise Exception("PDB code %s not found" % code)

        with open(pdb_path) as h:
            pdb_model = PDB(code=code, experiment=str(entry.EXPERIMENT), text=h.read())

        resolution = None
        try:
            resolution = float(entry.RESOLUTION)
        except:
            resolution = 20
        finally:
            if resolution and not math.isnan(resolution):
                pdb_model.resolution = resolution
        pdb_model.save()
        return pdb_model

    def _process_chain_residues(self, pdb_model, chain):
        idx = 0
        with transaction.atomic():
            residues = []
            for residue in chain.get_residues():
                residue_model = Residue(pdb=pdb_model, chain=chain.id, resid=residue.id[1],
                                        icode=residue.id[2],
                                        type="R" if not residue.id[0].strip() else residue.id[
                                            0].strip(),
                                        resname=residue.resname.strip(), disordered=residue.is_disordered())
                if is_aa(residue, standard=True):
                    residue_model.seq_order = idx
                    idx += 1
                residues.append(residue_model)
            Residue.objects.bulk_create(residues)

    def _process_chain_atoms(self, code, chain):
        with transaction.atomic():
            residues = {"_".join([str(x.resid), x.icode, x.resname]): x
                        for x in Residue.objects.filter(pdb__code=code, chain=chain.id)}
            atoms = []
            for residue in chain.get_residues():
                resid = "_".join([str(residue.id[1]), residue.id[2], residue.resname])
                if resid in residues:
                    residue_model = residues[resid]
                    for atom in list(residue):
                        if atom.is_disordered():
                            for altLoc, a in atom.child_dict.items():
                                atm = Atom(residue=residue_model, serial=a.serial_number, name=a.id,
                                           x=float(a.coord[0]), y=float(a.coord[1]),
                                           z=float(a.coord[2]), altLoc=altLoc,
                                           occupancy=float(a.occupancy), bfactor=float(a.bfactor),
                                           element=a.element)
                                atoms.append(atm)
                        else:
                            atm = Atom(residue=residue_model, serial=atom.serial_number, name=atom.id,
                                       x=float(atom.coord[0]), y=float(atom.coord[1]),
                                       z=float(atom.coord[2]), altLoc=" ",
                                       occupancy=float(atom.occupancy), bfactor=float(atom.bfactor),
                                       element=atom.element)
                            atoms.append(atm)
            Atom.objects.bulk_create(sorted(atoms, key=lambda x: x.serial))

    def update_entry_data(self, code, pdb_path):
        pdb_model = PDB.objects.get(code=code)
        p = PDBParser(PERMISSIVE=True, QUIET=True)
        chains = list(p.get_structure(code, pdb_path)[0].get_chains())
        for chain in tqdm(chains):
            self._process_chain_residues(pdb_model, chain)
            self._process_chain_atoms(pdb_model, chain)




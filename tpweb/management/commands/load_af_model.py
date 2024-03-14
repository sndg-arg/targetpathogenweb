import os
import shutil
import sys
import traceback
import gzip
import tempfile

from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom
import subprocess as sp


def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):
        parser.add_argument('struct_name')
        parser.add_argument('pdb_file')
        parser.add_argument('seq_name')
        parser.add_argument('--tmp', default="/tmp/load_pdb")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        seqstore = SeqStore(options['datadir'])
        code = options["struct_name"]

        be = Bioentry.objects.filter(accession=options["seq_name"])

        assert os.path.exists(options["pdb_file"]), f'"{options["pdb_file"]}" does not exists!'
        self.stderr.write(f"Holi")
        if not be.exists():
            self.stderr.write(f"bioentry {code} does not exists")
            sys.exit(1)

        be = be.get()
        genome = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
        pdb_model_qs = PDB.objects.filter(code=code,
                                          experiment="AF")
        if options["overwrite"]:
            self.stderr.write(f"deleting... {code} ")
            pdb_model_qs.delete()
        if pdb_model_qs.exists():
            self.stderr.write(f"structure {code} already exists")
            sys.exit(1)
        else:
            try:
                pdb_model = PDB(code=code,
                                experiment="AF")
                pdb_model.save()
                self.load_pdb_file(pdb_model, options["pdb_file"])
                BioentryStructure(bioentry=be, pdb=pdb_model).save()

            except IOError as ex:
                traceback.print_exc()
                self.stderr.write("error processing pockets from %s: %s" % (options["struct_name"], str(ex)))
            except Exception as ex:
                traceback.print_exc()
                raise CommandError(ex)

            if not os.path.exists(seqstore.structure_dir(genome, be.name)):
                os.makedirs(seqstore.structure_dir(genome, be.accession))

            if not options["pdb_file"].endswith(".gz"):
                th = tempfile.NamedTemporaryFile(dir='/tmp', delete=False)
                pdb_file = th.name
                th.close()
                sp.call(f'cat {options["pdb_file"]} | gzip > {pdb_file}', shell=True)
            else:
                pdb_file = options["pdb_file"]

            shutil.copy(pdb_file,
                        seqstore.structure(genome, be.accession, code))

        self.stderr.write(f"done processing: {code} ")

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

    def load_pdb_file(self, pdb_model, pdb_path):

        p = PDBParser(PERMISSIVE=True, QUIET=True)
        if pdb_path.endswith(".gz"):
            th = tempfile.NamedTemporaryFile(dir='/tmp', delete=False)
            with gzip.open(pdb_path) as h:
                th.write(h.read())
                pdb_path = th.name
            th.close()

        chains = list(p.get_structure("X", pdb_path)[0].get_chains())
        for chain in tqdm(chains):
            self._process_chain_residues(pdb_model, chain)
            self._process_chain_atoms(pdb_model, chain)

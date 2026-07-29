import os
import shutil
import sys
import traceback
import gzip
import tempfile

from Bio.PDB.PDBParser import PDBParser
from Bio.PDB.MMCIFParser import MMCIFParser
from Bio.PDB.Polypeptide import is_aa
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom


def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


def store_structure_file(pdb_file, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if pdb_file.endswith(".gz"):
        shutil.copyfile(pdb_file, destination)
    else:
        with open(pdb_file, "rb") as source, gzip.open(destination, "wb") as target:
            shutil.copyfileobj(source, target)
    os.chmod(destination, 0o644)


class Command(BaseCommand):
    help = 'Imports a PDB'

    def add_arguments(self, parser):
        parser.add_argument('struct_name')
        parser.add_argument('pdb_file')
        parser.add_argument('seq_name')
        parser.add_argument('--tmp', default="/tmp/load_pdb")
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")
        parser.add_argument('--experiment', default=None,
                            help="Force experiment type (AF, CF, EX). Auto-detected if not set.")

    def handle(self, *args, **options):
        seqstore = SeqStore(options['datadir'])
        code = options["struct_name"]

        be = Bioentry.objects.filter(accession=options["seq_name"])


        if not os.path.exists(options["pdb_file"]):
            self.stderr.write(f"path pdb {code} does not exists")
            sys.exit(0)
        if not be.exists():
            self.stderr.write(f"bioentry {code} does not exists")
            sys.exit(1)

        be = be.get()
        genome = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
        forced_experiment = (options.get("experiment") or "").strip().upper() or None
        if forced_experiment:
            pdb_model_qs = PDB.objects.filter(code=code, experiment=forced_experiment)
        else:
            pdb_model_qs = PDB.objects.filter(code=code, experiment__in=("AF", "CF"))
        if options["overwrite"]:
            self.stderr.write(f"deleting... {code} ")
            pdb_model_qs.delete()
        if pdb_model_qs.exists():
            self.stderr.write(f"structure {code} already exists")
            sys.exit(1)
        else:
            if forced_experiment:
                experiment = forced_experiment
            else:
                pdb_dir = os.path.dirname(options["pdb_file"])
                uniprot_file = os.path.join(pdb_dir, f"{code}_uniprot.txt")
                experiment = "AF" if os.path.exists(uniprot_file) else "CF"
            try:
                pdb_model = PDB(code=code,
                                experiment=experiment)
                pdb_model.save()
                self.load_pdb_file(pdb_model, options["pdb_file"])
                BioentryStructure(bioentry=be, pdb=pdb_model).save()

            except IOError as ex:
                traceback.print_exc()
                self.stderr.write("error processing pockets from %s: %s" % (options["struct_name"], str(ex)))
            except Exception as ex:
                traceback.print_exc()
                raise CommandError(ex)

            #if not os.path.exists(seqstore.structure_dir(genome, be.accession)):
            #    os.makedirs(seqstore.structure_dir(genome, be.accession))

            store_structure_file(
                options["pdb_file"],
                seqstore.structure(genome, be.accession, code),
            )

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
            # MMCIFParser (unlike PDBParser) leaves Atom.serial_number unset --
            # Atom.serial is NOT NULL, so synthesize a stable per-chain counter
            # for those. Classic .pdb files already carry a real serial_number
            # from PDBParser, so this fallback never fires on that path and
            # existing (bacteria) ingestion is unaffected.
            next_serial = 1

            def _resolve_serial(real_serial):
                nonlocal next_serial
                if real_serial is not None:
                    next_serial = max(next_serial, real_serial + 1)
                    return real_serial
                serial = next_serial
                next_serial += 1
                return serial

            for residue in chain.get_residues():
                resid = "_".join([str(residue.id[1]), residue.id[2], residue.resname])
                if resid in residues:
                    residue_model = residues[resid]
                    for atom in list(residue):
                        if atom.is_disordered():
                            for altLoc, a in atom.child_dict.items():
                                atm = Atom(residue=residue_model, serial=_resolve_serial(a.serial_number), name=a.id,
                                           x=float(a.coord[0]), y=float(a.coord[1]),
                                           z=float(a.coord[2]), altLoc=altLoc,
                                           occupancy=float(a.occupancy), bfactor=float(a.bfactor),
                                           element=a.element)
                                atoms.append(atm)
                        else:
                            atm = Atom(residue=residue_model, serial=_resolve_serial(atom.serial_number), name=atom.id,
                                       x=float(atom.coord[0]), y=float(atom.coord[1]),
                                       z=float(atom.coord[2]), altLoc=" ",
                                       occupancy=float(atom.occupancy), bfactor=float(atom.bfactor),
                                       element=atom.element)
                            atoms.append(atm)
            Atom.objects.bulk_create(sorted(
                atoms,
                key=lambda x: (
                    x.serial is None,
                    x.serial or 0,
                    x.residue.resid,
                    x.name,
                    x.x,
                    x.y,
                    x.z,
                ),
            ))

    def load_pdb_file(self, pdb_model, pdb_path):

        is_cif = pdb_path.lower().endswith((".cif", ".cif.gz"))
        parser = MMCIFParser(QUIET=True) if is_cif else PDBParser(PERMISSIVE=True, QUIET=True)
        if pdb_path.endswith(".gz"):
            th = tempfile.NamedTemporaryFile(dir='/tmp', delete=False)
            with gzip.open(pdb_path) as h:
                th.write(h.read())
                pdb_path = th.name
            th.close()

        if is_cif:
            pdb_path = self._sanitize_cif(pdb_path)

        chains = list(parser.get_structure("X", pdb_path)[0].get_chains())
        for chain in tqdm(chains):
            self._process_chain_residues(pdb_model, chain)
            self._process_chain_atoms(pdb_model, chain)

    @staticmethod
    def _sanitize_cif(pdb_path):
        """Biopython's MMCIF2Dict tokenizer raises "Opening quote in middle of
        word" on a bare apostrophe inside an ATOM/HETATM row -- nucleotide
        prime-notation atom names (O5', C1', ...), common in ATP/nucleotide
        ligands, aren't valid under CIF's quoting rules even though they're a
        real atom-naming convention. target-human-web's own 3Dmol.js viewer
        hit the identical parser bug client-side and works around it the same
        way (sanitizeCif(): swap ' for * on those rows only)."""
        with open(pdb_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        changed = False
        for i, line in enumerate(lines):
            if (line.startswith("ATOM") or line.startswith("HETATM")) and "'" in line:
                lines[i] = line.replace("'", "*")
                changed = True
        if not changed:
            return pdb_path
        th = tempfile.NamedTemporaryFile(mode="w", suffix=".cif", dir="/tmp", delete=False, encoding="utf-8")
        th.writelines(lines)
        th.close()
        return th.name

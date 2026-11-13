"""Import a completed monomer model only when its sequence matches the genome."""

from pathlib import Path
import shutil

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


AMINO_ACIDS = dict(
    zip(
        "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL SEC PYL UNK".split(),
        "ARNDCQEGHILKMFPSTWYVUOX",
        strict=True,
    )
)


def model_sequence(path):
    residues = {}
    models = 0
    with Path(path).open(encoding="ascii") as handle:
        for line in handle:
            if line.startswith("MODEL"):
                models += 1
                if models > 1:
                    raise CommandError("Expected a single-model ColabFold PDB.")
            if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
                continue
            if line[16:17] not in {" ", "A"}:
                continue
            name = line[17:20].strip()
            if name not in AMINO_ACIDS:
                raise CommandError(f"Unrecognized amino acid in model: {name}")
            key = (line[21:22], line[22:26], line[26:27])
            value = AMINO_ACIDS[name]
            if key in residues and residues[key] != value:
                raise CommandError("Conflicting residues in ColabFold model.")
            residues[key] = value
    if not residues or len({key[0] for key in residues}) != 1:
        raise CommandError("Expected one nonempty protein chain in the model.")
    return "".join(residues.values())


class Command(BaseCommand):
    help = (
        "Import an exact-sequence completed ColabFold monomer without replacing an existing model."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("locus_tag")
        parser.add_argument("pdb_file")
        parser.add_argument("--datadir", default="/app/targetpathogenweb/data")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        from bioseq.models.Biodatabase import Biodatabase
        from bioseq.models.Bioentry import Bioentry
        from tpweb.models.BioentryStructure import BioentryStructure
        from tpweb.models.pdb import PDB
        from tpweb.services.structure_files import compute_folder_path

        locus = options["locus_tag"]
        if (
            not locus
            or any(character in locus for character in ("/", "\\", "\x00"))
            or locus in {".", ".."}
        ):
            raise CommandError("Invalid locus tag.")
        protein = (
            Bioentry.objects.select_related("seq")
            .filter(
                biodatabase__name=options["genome_name"] + Biodatabase.PROT_POSTFIX,
                accession=locus,
            )
            .first()
        )
        if protein is None:
            raise CommandError("Protein not found in the specified genome.")
        path = Path(options["pdb_file"])
        expected = str(protein.seq.seq).strip().upper().rstrip("*")
        if model_sequence(path) != expected:
            raise CommandError("Model sequence differs from the current protein; nothing imported.")
        if BioentryStructure.objects.filter(bioentry=protein, pdb__experiment="CF").exists():
            self.stdout.write(f"{locus}: existing ColabFold model preserved.")
            return
        if Bioentry.objects.filter(accession=locus).count() != 1:
            raise CommandError(
                "The existing model loader requires an unambiguous locus across genomes."
            )
        if PDB.objects.filter(code=locus, experiment="CF").exists():
            raise CommandError(
                "An unlinked structure with this code already exists; inspect before importing."
            )
        if not options["apply"]:
            self.stdout.write(
                f"{locus}: exact sequence verified ({len(expected)} residues); no data changed."
            )
            return
        destination = (
            Path(compute_folder_path(options["datadir"], options["genome_name"]))
            / "alphafold"
            / locus
            / f"{locus}_af.pdb"
        )
        if destination.exists() and destination.read_bytes() != path.read_bytes():
            raise CommandError("A different workspace PDB already exists; it was preserved.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() != path.resolve():
            shutil.copyfile(path, destination)
        with transaction.atomic():
            call_command(
                "load_af_model",
                locus,
                str(destination),
                locus,
                experiment="CF",
                datadir=options["datadir"],
                stdout=self.stdout,
            )
            if not BioentryStructure.objects.filter(
                bioentry=protein, pdb__code=locus, pdb__experiment="CF"
            ).exists():
                raise CommandError(
                    "Model import verification failed; database changes rolled back."
                )
        self.stdout.write(f"{locus}: verified ColabFold model imported ({len(expected)} residues).")

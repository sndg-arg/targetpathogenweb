import math
import os
import requests
from collections import defaultdict

from Bio.PDB import MMCIFParser, PDBIO
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB
from tpweb.services.experimental_structures import _download_pdb, _update_structure_link
from tpweb.management.commands.load_af_model import store_structure_file


DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
SOURCE_FIELDS = ("best_fpocket_structure", "best_p2rank_structure")
RCSB_CIF_URL = "https://files.rcsb.org/download/{pdb_id}.cif"


def _clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def _is_pdb_code(value):
    value = _clean(value).upper()
    return len(value) == 4 and value.isalnum()


def _folder_path(datadir, genome_name):
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)



def _download_cif_as_pdb(pdb_id, dest_path):
    """Download an RCSB mmCIF file and convert it to legacy PDB format."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    cif_path = f"{dest_path}.cif"
    for identifier in (pdb_id.upper(), pdb_id.lower()):
        url = RCSB_CIF_URL.format(pdb_id=identifier)
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            with open(cif_path, "wb") as handle:
                handle.write(response.content)

            parser = MMCIFParser(QUIET=True)
            structure = parser.get_structure(pdb_id.upper(), cif_path)
            writer = PDBIO()
            writer.set_structure(structure)
            writer.save(dest_path)
            return os.path.exists(dest_path) and os.path.getsize(dest_path) > 100
        except Exception:
            continue
    return False

class Command(BaseCommand):
    help = (
        "Backfill missing experimental PDB structures selected by curated "
        "best_fpocket_structure/best_p2rank_structure score fields."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--datadir",
            default=DEFAULT_DATA_DIR,
            help="Base data directory. Default: %(default)s",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report missing selected PDB structures without downloading or loading.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Load at most N missing protein/PDB links.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        dry_run = options["dry_run"]
        limit = options["limit"]

        db_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=db_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {db_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_by_id = {protein.bioentry_id: protein for protein in proteins}
        protein_ids = set(protein_by_id)
        if not protein_ids:
            self.stdout.write("No proteins found.")
            return

        selected = defaultdict(set)
        for spv in ScoreParamValue.objects.filter(
            bioentry_id__in=protein_ids,
            score_param__name__in=SOURCE_FIELDS,
        ).select_related("score_param"):
            source = _clean(spv.value if spv.value else spv.numeric_value).upper()
            if _is_pdb_code(source):
                selected[(spv.bioentry_id, source)].add(spv.score_param.name)

        if not selected:
            self.stdout.write(f"No selected PDB sources found for {genome_name}.")
            return

        existing = set(
            BioentryStructure.objects.filter(
                bioentry_id__in=protein_ids,
                pdb__experiment="EX",
            ).values_list("bioentry_id", "pdb__code")
        )
        existing = {(bioentry_id, _clean(code).upper()) for bioentry_id, code in existing}

        to_load = [
            (protein_id, pdb_id, sorted(fields))
            for (protein_id, pdb_id), fields in sorted(
                selected.items(),
                key=lambda item: (protein_by_id[item[0][0]].accession, item[0][1]),
            )
            if (protein_id, pdb_id) not in existing
        ]
        if limit is not None:
            to_process = to_load[:limit]
        else:
            to_process = to_load

        self.stdout.write(self.style.MIGRATE_HEADING(f"Selected PDB backfill for {genome_name}"))
        self.stdout.write(f"Selected protein/PDB links: {len(selected)}")
        self.stdout.write(f"Already loaded as EX: {len(selected) - len(to_load)}")
        self.stdout.write(f"Missing selected PDB links: {len(to_load)}")
        if limit is not None:
            self.stdout.write(f"Processing limit: {len(to_process)}/{len(to_load)}")

        if dry_run:
            for protein_id, pdb_id, fields in to_process[:50]:
                protein = protein_by_id[protein_id]
                self.stdout.write(f"  would load {protein.accession} {pdb_id} ({', '.join(fields)})")
            if len(to_process) > 50:
                self.stdout.write(f"  ... {len(to_process) - 50} more")
            return

        folder_path = _folder_path(datadir, genome_name)
        exp_dir = os.path.join(folder_path, "experimental_selected")
        seqstore = SeqStore(datadir)

        downloaded = linked = skipped = failed = 0
        for protein_id, pdb_id, fields in to_process:
            protein = protein_by_id[protein_id]
            locus_tag = protein.accession
            dest_dir = os.path.join(exp_dir, locus_tag)
            dest_path = os.path.join(dest_dir, f"{pdb_id}.pdb")
            self.stdout.write(f"Loading {locus_tag} {pdb_id} ({', '.join(fields)})")

            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 100:
                pass
            elif _download_pdb(pdb_id, dest_path) or _download_cif_as_pdb(pdb_id, dest_path):
                downloaded += 1
            else:
                skipped += 1
                self.stderr.write(f"  skipped download failed: {locus_tag} {pdb_id}")
                continue

            try:
                pdb_obj = PDB.objects.filter(code__iexact=pdb_id, experiment="EX").first()
                if pdb_obj is None:
                    call_command(
                        "load_af_model",
                        pdb_id,
                        dest_path,
                        locus_tag,
                        experiment="EX",
                        datadir=datadir,
                    )
                    pdb_obj = PDB.objects.get(code__iexact=pdb_id, experiment="EX")

                xref = ExperimentalStructureXref.objects.filter(
                    bioentry=protein,
                    pdb_id__iexact=pdb_id,
                ).first()
                if xref is None:
                    xref = ExperimentalStructureXref(bioentry=protein, pdb_id=pdb_id)
                _update_structure_link(xref, pdb_obj)
                store_structure_file(dest_path, seqstore.structure(genome_name, locus_tag, pdb_obj.code))
                linked += 1
            except SystemExit as exc:
                if exc.code == 0:
                    linked += 1
                else:
                    failed += 1
                    self.stderr.write(f"  load_af_model exited {exc.code}: {locus_tag} {pdb_id}")
            except Exception as exc:
                failed += 1
                self.stderr.write(f"  failed {locus_tag} {pdb_id}: {exc}")

        self.stdout.write("")
        self.stdout.write(f"Downloaded: {downloaded}")
        self.stdout.write(f"Loaded/linked: {linked}")
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write(f"Failed: {failed}")

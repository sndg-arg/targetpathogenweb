import gzip
import math
import os
import shutil
import tarfile
import tempfile
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDBResidueSet
from tpweb.services.structure_files import structure_file_path


DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
SELECTED_FIELDS = (
    ("fpocket", "best_fpocket_structure", "Druggability", "fpocket_pocket", "FPocketPocket"),
    ("p2rank", "best_p2rank_structure", "p2rank_probability", "p2rank_pocket", "P2RankPocket"),
)
MANIFEST_COLUMNS = [
    "genome", "locus", "pdb_code", "chain", "need_fpocket", "need_p2rank",
    "fpocket_score", "fpocket_pocket", "p2rank_score", "p2rank_pocket", "input_pdb",
]


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


def _write_plain_pdb(source_path, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if source_path.endswith(".gz"):
        with gzip.open(source_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(source_path, dest_path)
    os.chmod(dest_path, 0o644)


def _fallback_structure_path(folder_path, locus, pdb_code):
    candidates = [
        os.path.join(folder_path, "experimental_selected", locus, f"{pdb_code}.pdb"),
        os.path.join(folder_path, "experimental", locus, f"{pdb_code}.pdb"),
        os.path.join(folder_path, "structures", locus, f"{pdb_code}.pdb.gz"),
        os.path.join(folder_path, "structures", locus, f"{pdb_code}.pdb"),
    ]
    for path in candidates:
        if os.path.exists(path) and os.path.getsize(path) > 100:
            return path
    return ""


class Command(BaseCommand):
    help = "Export selected PDB structures missing FPocket/P2Rank pockets for remote SLURM processing."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--datadir",
            default=DEFAULT_DATA_DIR,
            help="Base data directory. Default: %(default)s",
        )
        parser.add_argument(
            "--output-dir",
            default=None,
            help="Output directory for manifest and tarball. Defaults to <genome data>/selected_pdb_pocket_jobs.",
        )
        parser.add_argument(
            "--include-complete",
            action="store_true",
            help="Export selected PDBs even if both selected pocket methods are already loaded.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        folder_path = _folder_path(datadir, genome_name)
        output_dir = options["output_dir"] or os.path.join(folder_path, "selected_pdb_pocket_jobs")
        include_complete = options["include_complete"]

        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=proteome_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {proteome_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_accessions = dict(proteins.values_list("bioentry_id", "accession"))
        protein_ids = set(protein_accessions)
        if not protein_ids:
            self.stdout.write("No proteins found.")
            return

        score_names = set()
        for _method, source_field, score_field, pocket_field, _residue_set in SELECTED_FIELDS:
            score_names.update([source_field, score_field, pocket_field])

        scores = defaultdict(dict)
        for spv in ScoreParamValue.objects.filter(
            bioentry_id__in=protein_ids,
            score_param__name__in=score_names,
        ).select_related("score_param"):
            value = spv.value if spv.value else (
                str(spv.numeric_value) if spv.numeric_value is not None else ""
            )
            scores[spv.bioentry_id][spv.score_param.name] = _clean(value)

        loaded = {}
        pdb_ids = set()
        for link in BioentryStructure.objects.filter(
            bioentry_id__in=protein_ids,
            pdb__experiment="EX",
        ).select_related("pdb", "bioentry"):
            code = _clean(link.pdb.code).upper()
            loaded[(link.bioentry_id, code)] = link
            pdb_ids.add(link.pdb_id)

        pockets_by_type = defaultdict(set)
        if pdb_ids:
            for pdb_id, residue_set_name in PDBResidueSet.objects.filter(
                pdb_id__in=pdb_ids,
                residue_set__name__in=[field[-1] for field in SELECTED_FIELDS],
            ).values_list("pdb_id", "residue_set__name"):
                pockets_by_type[residue_set_name].add(pdb_id)

        jobs = {}
        for protein_id, accession in protein_accessions.items():
            row_scores = scores.get(protein_id, {})
            for method, source_field, score_field, pocket_field, residue_set_name in SELECTED_FIELDS:
                source = row_scores.get(source_field, "")
                if not _is_pdb_code(source):
                    continue
                pdb_code = source.upper()
                link = loaded.get((protein_id, pdb_code))
                if link is None:
                    continue

                has_pockets = link.pdb_id in pockets_by_type[residue_set_name]
                key = (protein_id, pdb_code)
                job = jobs.setdefault(key, {
                    "genome": genome_name,
                    "locus": accession,
                    "pdb_code": pdb_code,
                    "chain": link.chain or "",
                    "need_fpocket": False,
                    "need_p2rank": False,
                    "fpocket_score": "",
                    "fpocket_pocket": "",
                    "p2rank_score": "",
                    "p2rank_pocket": "",
                })
                if method == "fpocket":
                    job["fpocket_score"] = row_scores.get(score_field, "")
                    job["fpocket_pocket"] = row_scores.get(pocket_field, "")
                    job["need_fpocket"] = include_complete or not has_pockets
                else:
                    job["p2rank_score"] = row_scores.get(score_field, "")
                    job["p2rank_pocket"] = row_scores.get(pocket_field, "")
                    job["need_p2rank"] = include_complete or not has_pockets

        jobs = [job for job in jobs.values() if job["need_fpocket"] or job["need_p2rank"]]
        jobs.sort(key=lambda item: (item["locus"], item["pdb_code"]))

        os.makedirs(output_dir, exist_ok=True)
        manifest_path = os.path.join(output_dir, f"{genome_name}_selected_pdb_pockets.tsv")
        tar_path = os.path.join(output_dir, f"{genome_name}_selected_pdb_pockets.tar.gz")
        missing_files = []

        with tempfile.TemporaryDirectory(prefix="selected_pdb_pockets_") as tmp_dir:
            input_root = os.path.join(tmp_dir, "input")
            os.makedirs(input_root, exist_ok=True)

            for job in jobs:
                locus = job["locus"]
                pdb_code = job["pdb_code"]
                try:
                    source_path = structure_file_path(genome_name, locus, pdb_code)
                except FileNotFoundError:
                    source_path = _fallback_structure_path(folder_path, locus, pdb_code)
                if not source_path:
                    missing_files.append((locus, pdb_code))
                    continue

                job_dir_name = f"{locus}__{pdb_code}"
                rel_pdb = os.path.join("input", job_dir_name, f"{pdb_code}.pdb")
                dest_path = os.path.join(tmp_dir, rel_pdb)
                _write_plain_pdb(source_path, dest_path)
                job["input_pdb"] = rel_pdb.replace(os.sep, "/")

            export_jobs = [job for job in jobs if job.get("input_pdb")]
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write("\t".join(MANIFEST_COLUMNS) + "\n")
                for job in export_jobs:
                    handle.write("\t".join(str(job.get(column, "")) for column in MANIFEST_COLUMNS) + "\n")

            shutil.copyfile(manifest_path, os.path.join(tmp_dir, "manifest.tsv"))
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(os.path.join(tmp_dir, "manifest.tsv"), arcname="manifest.tsv")
                tar.add(input_root, arcname="input")

        self.stdout.write(self.style.MIGRATE_HEADING(f"Selected PDB pocket export for {genome_name}"))
        self.stdout.write(f"Jobs needing pockets: {len(jobs)}")
        self.stdout.write(f"Exported jobs: {len(jobs) - len(missing_files)}")
        self.stdout.write(f"Missing PDB files: {len(missing_files)}")
        if missing_files:
            for locus, pdb_code in missing_files[:25]:
                self.stdout.write(f"  missing file: {locus} {pdb_code}")
            if len(missing_files) > 25:
                self.stdout.write(f"  ... {len(missing_files) - 25} more")
        self.stdout.write(f"Manifest: {manifest_path}")
        self.stdout.write(f"Tarball : {tar_path}")

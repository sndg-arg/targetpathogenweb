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


def clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def norm_source(value):
    value = clean(value).upper()
    for prefix in ("AF_", "CB_"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def is_pdb_code(value):
    value = clean(value).upper()
    return len(value) == 4 and value.isalnum()


def is_alphafold_uniprot_source(value):
    value = clean(value).upper()
    if not value or is_pdb_code(value) or value.startswith("CB_"):
        return False
    if value.startswith("AF_") or value.startswith("A0A"):
        return True
    if len(value) == 6 and value[0].isalpha() and value[1].isdigit() and value[-1].isdigit():
        return True
    return False


def structure_code(accession):
    return f"AF_{clean(accession).upper()}"


def folder_path(datadir, genome_name):
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)


def is_expected_no_pockets(method, pocket):
    return method == "p2rank" and clean(pocket).lower() == "no_pockets"


def write_plain_pdb(source_path, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if source_path.endswith(".gz"):
        with gzip.open(source_path, "rb") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(source_path, dest_path)
    os.chmod(dest_path, 0o644)


def fallback_structure_path(folder, code):
    candidate = os.path.join(folder, "selected_alphafold_jobs", "models", f"{code}.pdb")
    if os.path.exists(candidate) and os.path.getsize(candidate) > 100:
        return candidate
    return ""


class Command(BaseCommand):
    help = "Export selected AlphaFold structures missing FPocket/P2Rank pockets for remote SLURM processing."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--datadir", default=DEFAULT_DATA_DIR)
        parser.add_argument(
            "--output-dir",
            default=None,
            help="Output directory for manifest and tarball. Defaults to <genome data>/selected_alphafold_pocket_jobs.",
        )
        parser.add_argument(
            "--include-complete",
            action="store_true",
            help="Export selected AlphaFold models even if requested pockets are already loaded.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        folder = folder_path(datadir, genome_name)
        output_dir = options["output_dir"] or os.path.join(folder, "selected_alphafold_pocket_jobs")
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
            scores[spv.bioentry_id][spv.score_param.name] = clean(value)
        loaded = {}
        pdb_ids = set()
        for link in BioentryStructure.objects.filter(
            bioentry_id__in=protein_ids,
            pdb__experiment="AF",
        ).select_related("pdb", "bioentry"):
            code = clean(link.pdb.code).upper()
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
        missing_structures = 0
        expected_no_pockets = 0
        selected_rows = 0

        for protein_id, locus in protein_accessions.items():
            row_scores = scores.get(protein_id, {})
            for method, source_field, score_field, pocket_field, residue_set_name in SELECTED_FIELDS:
                source = row_scores.get(source_field, "")
                if not is_alphafold_uniprot_source(source):
                    continue

                selected_rows += 1
                pocket = row_scores.get(pocket_field, "")
                if is_expected_no_pockets(method, pocket):
                    expected_no_pockets += 1
                    continue

                accession = norm_source(source)
                code = structure_code(accession)
                link = loaded.get((protein_id, code))
                if link is None:
                    missing_structures += 1
                    continue

                has_pockets = link.pdb_id in pockets_by_type[residue_set_name]
                key = (protein_id, code)
                job = jobs.setdefault(key, {
                    "genome": genome_name,
                    "locus": locus,
                    "pdb_code": code,
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
                    job["fpocket_pocket"] = pocket
                    job["need_fpocket"] = include_complete or not has_pockets
                else:
                    job["p2rank_score"] = row_scores.get(score_field, "")
                    job["p2rank_pocket"] = pocket
                    job["need_p2rank"] = include_complete or not has_pockets

        jobs = [job for job in jobs.values() if job["need_fpocket"] or job["need_p2rank"]]
        jobs.sort(key=lambda item: (item["locus"], item["pdb_code"]))

        os.makedirs(output_dir, exist_ok=True)
        manifest_path = os.path.join(output_dir, f"{genome_name}_selected_alphafold_pockets.tsv")
        tar_path = os.path.join(output_dir, f"{genome_name}_selected_alphafold_pockets.tar.gz")
        missing_files = []

        with tempfile.TemporaryDirectory(prefix=f"{genome_name}_selected_af_pockets_") as tmp_dir:
            input_root = os.path.join(tmp_dir, "input")
            os.makedirs(input_root, exist_ok=True)

            with open(manifest_path, "w", encoding="utf-8", newline="") as manifest:
                manifest.write("\t".join(MANIFEST_COLUMNS) + "\n")

                exported = 0
                for job in jobs:
                    locus = job["locus"]
                    pdb_code = job["pdb_code"]
                    try:
                        source_path = structure_file_path(genome_name, locus, pdb_code)
                    except FileNotFoundError:
                        source_path = fallback_structure_path(folder, pdb_code)
                    if not source_path or not os.path.exists(source_path):
                        source_path = fallback_structure_path(folder, pdb_code)

                    if not source_path or not os.path.exists(source_path):
                        missing_files.append((locus, pdb_code))
                        continue

                    job_dir_name = f"{locus}__{pdb_code}"
                    job_input_dir = os.path.join(input_root, job_dir_name)
                    os.makedirs(job_input_dir, exist_ok=True)
                    input_pdb = os.path.join(job_input_dir, f"{pdb_code}.pdb")
                    write_plain_pdb(source_path, input_pdb)

                    row = {
                        **job,
                        "need_fpocket": "1" if job["need_fpocket"] else "0",
                        "need_p2rank": "1" if job["need_p2rank"] else "0",
                        "input_pdb": f"input/{job_dir_name}/{pdb_code}.pdb",
                    }
                    manifest.write("\t".join(str(row.get(col, "")) for col in MANIFEST_COLUMNS) + "\n")
                    exported += 1

            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(manifest_path, arcname="manifest.tsv")
                if os.path.isdir(input_root):
                    tar.add(input_root, arcname="input")

        self.stdout.write(f"Selected AlphaFold pocket export for {genome_name}")
        self.stdout.write(f"Selected AlphaFold rows: {selected_rows}")
        self.stdout.write(f"Expected P2Rank no-pockets rows: {expected_no_pockets}")
        self.stdout.write(f"Selected rows missing loaded AlphaFold structure: {missing_structures}")
        self.stdout.write(f"Jobs needing pockets: {len(jobs)}")
        self.stdout.write(f"Exported jobs: {exported}")
        self.stdout.write(f"Missing PDB files: {len(missing_files)}")
        if missing_files:
            self.stdout.write("Missing file examples:")
            for locus, pdb_code in missing_files[:20]:
                self.stdout.write(f"  {locus} {pdb_code}")
        self.stdout.write(f"Manifest: {manifest_path}")
        self.stdout.write(f"Tarball : {tar_path}")

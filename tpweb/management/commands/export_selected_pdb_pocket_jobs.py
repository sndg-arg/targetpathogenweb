import ast
import csv
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
DEFAULT_STRUCTURE_COLUMN = "structure"
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
    return len(value) == 4 and value[0].isdigit() and value.isalnum()


def _parse_structure_candidates(value):
    value = _clean(value)
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = value.replace("{", "").replace("}", "").split(",")
    return sorted({
        _clean(candidate).strip("'\"").upper()
        for candidate in parsed
        if _is_pdb_code(candidate)
    })


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
        parser.add_argument(
            "--results-tsv",
            default=None,
            help=(
                "Optional curated results TSV. Used only with "
                "--include-structure-column to export PDB candidates listed "
                "in the TSV structure column."
            ),
        )
        parser.add_argument(
            "--include-structure-column",
            action="store_true",
            help=(
                "Also export PDB candidates from the curated TSV 'structure' "
                "column. This is opt-in because those PDBs are structural "
                "evidence records, not necessarily selected pocket-score sources."
            ),
        )
        parser.add_argument(
            "--structure-column",
            default=DEFAULT_STRUCTURE_COLUMN,
            help="Curated TSV column containing structure candidates. Default: %(default)s",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        folder_path = _folder_path(datadir, genome_name)
        output_dir = options["output_dir"] or os.path.join(folder_path, "selected_pdb_pocket_jobs")
        include_complete = options["include_complete"]
        results_tsv = options["results_tsv"]
        include_structure_column = options["include_structure_column"]
        structure_column = options["structure_column"]

        if include_structure_column and not results_tsv:
            raise CommandError("--include-structure-column requires --results-tsv.")
        if results_tsv and not os.path.isfile(results_tsv):
            raise CommandError(f"Results TSV not found: {results_tsv}")

        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        try:
            db = Biodatabase.objects.get(name=proteome_name)
        except Biodatabase.DoesNotExist as exc:
            raise CommandError(f"Protein database not found: {proteome_name}") from exc

        proteins = Bioentry.objects.filter(biodatabase=db).only("bioentry_id", "accession")
        protein_accessions = dict(proteins.values_list("bioentry_id", "accession"))
        protein_by_accession = {accession: protein_id for protein_id, accession in protein_accessions.items()}
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

        missing_tsv_genes = 0
        if include_structure_column:
            with open(results_tsv, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                if "gene" not in (reader.fieldnames or []):
                    raise CommandError("Results TSV must have a 'gene' column.")
                if structure_column not in (reader.fieldnames or []):
                    raise CommandError(
                        f"Results TSV does not have structure column '{structure_column}'."
                    )

                for row in reader:
                    accession = _clean(row.get("gene"))
                    protein_id = protein_by_accession.get(accession)
                    if protein_id is None:
                        missing_tsv_genes += 1
                        continue
                    for pdb_code in _parse_structure_candidates(row.get(structure_column)):
                        link = loaded.get((protein_id, pdb_code))
                        if link is None:
                            continue
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
                        job["need_fpocket"] = (
                            job["need_fpocket"]
                            or include_complete
                            or link.pdb_id not in pockets_by_type["FPocketPocket"]
                        )
                        job["need_p2rank"] = (
                            job["need_p2rank"]
                            or include_complete
                            or link.pdb_id not in pockets_by_type["P2RankPocket"]
                        )

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
        if include_structure_column:
            self.stdout.write(f"Included curated TSV column: {structure_column}")
            if missing_tsv_genes:
                self.stdout.write(
                    self.style.WARNING(
                        f"TSV rows not found in TPW proteins: {missing_tsv_genes}"
                    )
                )
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
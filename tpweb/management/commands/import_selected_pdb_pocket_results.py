import csv
import gzip
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections import defaultdict

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from tpweb.management.commands import backfill_pockets_experimental as bpe
from tpweb.models.pdb import PDB, PDBResidueSet


DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
FP_RESIDUE_SET = "FPocketPocket"
P2_RESIDUE_SET = "P2RankPocket"
INFO_TO_TPW_PROPERTY = {
    "Score": "Score",
    "Druggability Score": "Druggability Score",
    "Number of Alpha Spheres": "Number of Alpha Spheres",
    "Total SASA": "Total SASA",
    "Polar SASA": "Polar SASA",
    "Apolar SASA": "Apolar SASA",
    "Volume": "Volume",
    "Mean local hydrophobic density": "Mean local hydrophobic density",
    "Mean alpha sphere radius": "Mean alpha sphere radius",
    "Mean alp. sph. solvent access": "Mean alp sph solvent access",
    "Mean alp sph solvent access": "Mean alp sph solvent access",
    "Apolar alpha sphere proportion": "Apolar alpha sphere proportion",
    "Hydrophobicity score": "Hydrophobicity score",
    "Volume score": "Volume score",
    "Polarity score": "Polarity score",
    "Charge score": "Charge score",
    "Proportion of polar atoms": "Proportion of polar atoms",
    "Alpha sphere density": "Alpha sphere density",
    "Cent. of mass - Alpha Sphere max dist": "Cent of mass - Alpha Sphere max dist",
    "Cent of mass - Alpha Sphere max dist": "Cent of mass - Alpha Sphere max dist",
    "Flexibility": "Flexibility",
}

def clean(value):
    return str(value or "").strip()


def as_bool(value):
    return clean(value).lower() in {"1", "true", "yes", "y"}


def genome_folder(datadir, genome_name):
    import math

    n = len(genome_name)
    folder = genome_name[math.floor(n / 2 - 1):math.floor(n / 2 + 2)]
    return os.path.join(datadir, folder, genome_name)


def safe_extract(tar, path):
    target = os.path.abspath(path)
    for member in tar.getmembers():
        member_path = os.path.abspath(os.path.join(path, member.name))
        if not (member_path == target or member_path.startswith(target + os.sep)):
            raise CommandError(f"Unsafe tar member path: {member.name}")
    tar.extractall(path)


def read_manifest(path):
    if not os.path.exists(path):
        raise CommandError(f"Manifest not found: {path}")
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def find_manifest(root):
    preferred = os.path.join(root, "manifest.tsv")
    if os.path.exists(preferred):
        return preferred

    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename == "manifest.tsv" or filename.endswith("_selected_pdb_pockets.tsv"):
                return os.path.join(dirpath, filename)
    return ""


def find_job_dir(root, locus, pdb_code):
    name = f"{locus}__{pdb_code}"
    candidates = [
        os.path.join(root, "output", name),
        os.path.join(root, name),
        os.path.join(root, "input", name),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate

    for dirpath, dirnames, _filenames in os.walk(root):
        if name in dirnames:
            return os.path.join(dirpath, name)
    return ""


def find_fpocket_dir(job_dir, pdb_code):
    for name in (f"{pdb_code}_out", f"{pdb_code.lower()}_out"):
        candidate = os.path.join(job_dir, name)
        if os.path.isdir(candidate):
            return candidate

    for dirpath, dirnames, _filenames in os.walk(job_dir):
        for dirname in dirnames:
            if dirname.endswith("_out"):
                return os.path.join(dirpath, dirname)
    return ""


def find_p2rank_dir(job_dir, pdb_code):
    for name in (f"{pdb_code}_p2rank", f"{pdb_code.lower()}_p2rank", "p2rank"):
        candidate = os.path.join(job_dir, name)
        if os.path.isdir(candidate):
            return candidate

    for dirpath, dirnames, filenames in os.walk(job_dir):
        if any(name.endswith("_predictions.csv") or name == "p2pocket.json.gz" for name in filenames):
            return dirpath
        for dirname in dirnames:
            if "p2rank" in dirname.lower():
                return os.path.join(dirpath, dirname)
    return ""


def has_residue_set(pdb_code, residue_set_name):
    pdb_ids = list(
        PDB.objects.filter(code__iexact=pdb_code, deprecated=False)
        .values_list("id", flat=True)
    )
    if not pdb_ids:
        return False

    return PDBResidueSet.objects.filter(
        pdb_id__in=pdb_ids,
        residue_set__name=residue_set_name,
    ).exists()


def fpocket_json_is_empty(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return False
    return data == []


def parse_fpocket_info(path):
    pockets = {}
    current = None
    if not os.path.exists(path):
        return pockets

    with open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = re.match(r"Pocket\s+(\d+)\s*:", line)
            if match:
                current = int(match.group(1))
                pockets[current] = {}
                continue
            if current is None or ":" not in line:
                continue

            raw_name, _sep, raw_value = line.partition(":")
            prop_name = INFO_TO_TPW_PROPERTY.get(raw_name.strip().rstrip("."))
            if not prop_name:
                continue
            try:
                pockets[current][prop_name] = float(raw_value.strip())
            except ValueError:
                continue
    return pockets


def parse_fpocket_alpha_lines(path):
    pockets = defaultdict(list)
    if not os.path.exists(path):
        return pockets

    with open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("HETATM") or "STP" not in line:
                continue
            try:
                pocket_number = int(line[22:26])
            except ValueError:
                continue
            pockets[pocket_number].append(line if line.endswith("\n") else line + "\n")
    return pockets


def parse_fpocket_atom_pdb(path):
    atoms = []
    residues = []
    if not os.path.exists(path):
        return atoms, residues

    with open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            serial = line[6:11].strip()
            if serial:
                atoms.append(serial)

            chain = line[21:22].strip()
            resid = line[22:26].strip()
            insertion = line[26:27].strip()
            if resid:
                residues.append(f"{chain}{resid}{insertion}")
    return atoms, residues


def parse_fpocket_atom_files(fpocket_dir):
    atoms_by_pocket = {}
    residues_by_pocket = {}
    pockets_dir = os.path.join(fpocket_dir, "pockets")
    if not os.path.isdir(pockets_dir):
        return atoms_by_pocket, residues_by_pocket

    for filename in sorted(os.listdir(pockets_dir)):
        match = re.match(r"pocket(\d+)_atm\.pdb$", filename)
        if not match:
            continue
        pocket_number = int(match.group(1))
        atoms, residues = parse_fpocket_atom_pdb(os.path.join(pockets_dir, filename))
        atoms_by_pocket[pocket_number] = atoms
        residues_by_pocket[pocket_number] = residues
    return atoms_by_pocket, residues_by_pocket


def fallback_fpocket_to_json(fpocket_dir):
    basename = os.path.basename(fpocket_dir)
    if basename.endswith("_out"):
        stem = basename[:-4]
    elif basename.endswith("_fpocket"):
        stem = basename[:-8]
    else:
        stem = basename
    out_pdb = os.path.join(fpocket_dir, f"{stem}_out.pdb")
    info_txt = os.path.join(fpocket_dir, f"{stem}_info.txt")

    properties_by_pocket = parse_fpocket_info(info_txt)
    alpha_lines_by_pocket = parse_fpocket_alpha_lines(out_pdb)
    atoms_by_pocket, residues_by_pocket = parse_fpocket_atom_files(fpocket_dir)

    pocket_numbers = sorted(
        set(properties_by_pocket)
        | set(alpha_lines_by_pocket)
        | set(atoms_by_pocket)
        | set(residues_by_pocket)
    )
    if not pocket_numbers:
        return None

    pocket_json = os.path.join(os.path.dirname(fpocket_dir), f"{basename}.fallback.json.gz")
    pockets = [
        {
            "number": number,
            "residues": residues_by_pocket.get(number, []),
            "as_lines": alpha_lines_by_pocket.get(number, []),
            "atoms": atoms_by_pocket.get(number, []),
            "properties": properties_by_pocket.get(number, {}),
        }
        for number in pocket_numbers
    ]

    with gzip.open(pocket_json, "wt", encoding="utf-8") as handle:
        json.dump(pockets, handle)
    try:
        os.chmod(pocket_json, 0o666)
    except OSError:
        pass
    return pocket_json


class Command(BaseCommand):
    help = "Import FPocket/P2Rank results for selected PDB pocket jobs."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--results-tar", required=True)
        parser.add_argument("--datadir", default=DEFAULT_DATA_DIR)
        parser.add_argument("--manifest", default=None)
        parser.add_argument("--keep-extracted", action="store_true")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        datadir = options["datadir"].rstrip("/\\")
        results_tar = options["results_tar"]
        force = options["force"]

        if not os.path.exists(results_tar):
            raise CommandError(f"Results tarball not found: {results_tar}")

        folder = genome_folder(datadir, genome_name)
        default_manifest = os.path.join(
            folder,
            "selected_pdb_pocket_jobs",
            f"{genome_name}_selected_pdb_pockets.tsv",
        )

        tmp_ctx = None
        if options["keep_extracted"]:
            extract_root = os.path.join(
                folder,
                "selected_pdb_pocket_jobs",
                "imported_results",
                os.path.splitext(os.path.basename(results_tar))[0],
            )
            if os.path.isdir(extract_root):
                shutil.rmtree(extract_root)
            os.makedirs(extract_root, exist_ok=True)
        else:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="selected_pdb_pocket_results_")
            extract_root = tmp_ctx.name

        try:
            with tarfile.open(results_tar, "r:gz") as tar:
                safe_extract(tar, extract_root)

            manifest_path = options["manifest"] or find_manifest(extract_root) or default_manifest
            rows = read_manifest(manifest_path)

            fp_loaded = fp_skipped = fp_failed = 0
            p2_loaded = p2_skipped = p2_failed = 0
            missing_jobs = 0

            self.stdout.write(self.style.MIGRATE_HEADING(
                f"Selected PDB pocket import for {genome_name}"
            ))
            self.stdout.write(f"Rows in manifest: {len(rows)}")
            self.stdout.write(f"Results: {extract_root}")
            self.stdout.write(f"Manifest: {manifest_path}")

            for row in rows:
                if clean(row.get("genome")) and clean(row.get("genome")) != genome_name:
                    continue

                locus = clean(row.get("locus"))
                pdb_code = clean(row.get("pdb_code")).upper()
                if not locus or not pdb_code:
                    continue

                job_dir = find_job_dir(extract_root, locus, pdb_code)
                if not job_dir:
                    missing_jobs += 1
                    self.stderr.write(f"missing job output: {locus} {pdb_code}")
                    continue

                if as_bool(row.get("need_fpocket")):
                    if not force and has_residue_set(pdb_code, FP_RESIDUE_SET):
                        fp_skipped += 1
                    else:
                        fpocket_dir = find_fpocket_dir(job_dir, pdb_code)
                        if not fpocket_dir:
                            fp_failed += 1
                            self.stderr.write(f"missing FPocket output: {locus} {pdb_code}")
                        else:
                            pocket_json = bpe._fpocket_to_json(fpocket_dir)
                            if not pocket_json or fpocket_json_is_empty(pocket_json):
                                fallback_json = fallback_fpocket_to_json(fpocket_dir)
                                if fallback_json:
                                    self.stdout.write(f"FPocket fallback JSON used: {locus} {pdb_code}")
                                    pocket_json = fallback_json
                            if not pocket_json:
                                fp_failed += 1
                                self.stderr.write(f"FPocket JSON failed: {locus} {pdb_code}")
                            else:
                                try:
                                    call_command(
                                        "load_fpocket",
                                        pdb_code,
                                        pocket_json=pocket_json,
                                        datadir=datadir,
                                        verbosity=0,
                                    )
                                    fp_loaded += 1
                                except Exception as exc:
                                    fp_failed += 1
                                    self.stderr.write(f"FPocket load failed: {locus} {pdb_code}: {exc}")

                if as_bool(row.get("need_p2rank")):
                    if not force and has_residue_set(pdb_code, P2_RESIDUE_SET):
                        p2_skipped += 1
                    else:
                        p2rank_dir = find_p2rank_dir(job_dir, pdb_code)
                        if not p2rank_dir:
                            p2_failed += 1
                            self.stderr.write(f"missing P2Rank output: {locus} {pdb_code}")
                        else:
                            pocket_json = bpe._p2rank_to_json(p2rank_dir, pdb_code)
                            if not pocket_json:
                                p2_failed += 1
                                self.stderr.write(f"P2Rank JSON failed: {locus} {pdb_code}")
                            else:
                                try:
                                    call_command(
                                        "load_fpocket",
                                        pdb_code,
                                        pocket_json=pocket_json,
                                        P2rank_pocket=True,
                                        datadir=datadir,
                                        verbosity=0,
                                    )
                                    p2_loaded += 1
                                except Exception as exc:
                                    p2_failed += 1
                                    self.stderr.write(f"P2Rank load failed: {locus} {pdb_code}: {exc}")

            self.stdout.write("")
            self.stdout.write(f"Missing job dirs: {missing_jobs}")
            self.stdout.write(f"FPocket loaded: {fp_loaded}")
            self.stdout.write(f"FPocket skipped existing: {fp_skipped}")
            self.stdout.write(f"FPocket failed: {fp_failed}")
            self.stdout.write(f"P2Rank loaded: {p2_loaded}")
            self.stdout.write(f"P2Rank skipped existing: {p2_skipped}")
            self.stdout.write(f"P2Rank failed: {p2_failed}")

        finally:
            if tmp_ctx is not None:
                tmp_ctx.cleanup()

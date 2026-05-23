"""
Run FPocket + P2Rank + druggability on crystal (EX) structures that were
loaded by backfill_experimental_structures but have no pocket data yet.

Steps per protein:
  1. FPocket  — Docker image ezequieljsosa/fpocket
  2. FPocket → JSON conversion (SNDG.Structure.FPocket 2json)
  3. Load FPocket pockets (load_fpocket management command)
  4. P2Rank   — Docker image mcpalumbo/p2rank:latest
  5. P2Rank predictions → JSON (inline, mirrors p2rank_2_json logic)
  6. Load P2Rank pockets (load_fpocket --P2rank_pocket)

After all proteins in a genome: re-run druggability_2_csv.
"""

import gzip
import json
import logging
import math
import os
import subprocess
import shlex
import shutil

import pandas as pd
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")
PYTHON_BIN = "/opt/conda/envs/tpv2/bin/python"
CONTAINER_DATA_PREFIX = "/app/targetpathogenweb/data"
HOST_DATA_PREFIX = "/data/targetpathogen/data"


def _chain_tokens(chain):
    return [token.strip() for token in str(chain or "").replace("/", ",").split(",") if token.strip()]


def _pdb_chain_id(line):
    return line[21:22].strip()


def _filtered_pdb_for_chain(pdb_path, chain, locus_dir):
    """Return a PDB path filtered to the mapped protein chain(s), or original path."""
    chains = set(_chain_tokens(chain))
    if not chains:
        return pdb_path

    chain_suffix = "_".join(sorted(chains)).replace(" ", "_")
    base = os.path.splitext(os.path.basename(pdb_path))[0]
    filtered_path = os.path.join(locus_dir, f"{base}_chains_{chain_suffix}.pdb")
    if os.path.exists(filtered_path) and os.path.getsize(filtered_path) > 100:
        return filtered_path

    kept = 0
    with open(pdb_path, "rt", errors="replace") as src, open(filtered_path, "wt") as dst:
        for line in src:
            record = line[:6].strip()
            if record in {"ATOM", "ANISOU", "TER"}:
                if _pdb_chain_id(line) in chains:
                    dst.write(line)
                    kept += 1
            elif record == "HETATM":
                # Keep ligands/waters from the mapped chain. Blank-chain HETATM
                # records are kept because some PDB writers omit ligand chain IDs.
                if _pdb_chain_id(line) in chains or not _pdb_chain_id(line):
                    dst.write(line)
                    kept += 1
            elif record in {"MODEL", "ENDMDL", "END"}:
                dst.write(line)
    if kept == 0:
        logger.warning("Chain filter %s kept no atoms for %s; using full PDB", ",".join(sorted(chains)), pdb_path)
        try:
            os.remove(filtered_path)
        except OSError:
            pass
        return pdb_path
    return filtered_path


def _tool_safe_pdb_path(locus_dir, pdb_path):
    """Return a filename that external pocket tools can resolve inside /work."""
    basename = os.path.basename(pdb_path)
    safe_basename = basename.lower()
    if safe_basename == basename:
        return pdb_path

    safe_path = os.path.join(locus_dir, safe_basename)
    if not os.path.exists(safe_path) or os.path.getmtime(safe_path) < os.path.getmtime(pdb_path):
        shutil.copyfile(pdb_path, safe_path)
    return safe_path


def _docker_mount_source(path):
    """Translate container data paths to host paths for Docker socket mounts."""
    abs_path = os.path.abspath(path)
    if abs_path == CONTAINER_DATA_PREFIX or abs_path.startswith(f"{CONTAINER_DATA_PREFIX}/"):
        return abs_path.replace(CONTAINER_DATA_PREFIX, HOST_DATA_PREFIX, 1)
    return abs_path


def _docker_chmod_work_path(locus_dir, work_path):
    """Use the host Docker daemon to chmod files created by tool containers."""
    cmd = [
        "docker", "run",
        "--rm",
        "--entrypoint", "chmod",
        "-v", f"{_docker_mount_source(locus_dir)}:/work",
        "ezequieljsosa/fpocket",
        "-R", "a+rwX", work_path,
    ]
    return subprocess.run(cmd, capture_output=True, cwd=locus_dir)


def _run_fpocket(locus_dir, pdb_path):
    """Run FPocket via Docker. Returns path to output dir or None on failure."""
    pdb_path = _tool_safe_pdb_path(locus_dir, pdb_path)
    pdb_basename = os.path.splitext(os.path.basename(pdb_path))[0]
    out_dir = os.path.join(locus_dir, f"{pdb_basename}_out")

    if os.path.isdir(out_dir) and os.listdir(out_dir):
        logger.debug("FPocket output already exists for %s", pdb_basename)
        return out_dir

    pdb_basename_only = os.path.basename(pdb_path)
    cmd = [
        "docker", "run",
        "--rm", "-i",
        "-v", f"{_docker_mount_source(locus_dir)}:/work",
        "ezequieljsosa/fpocket",
        "fpocket", "-f", f"/work/{pdb_basename_only}",
    ]
    logger.info("Running FPocket for %s", pdb_basename)
    result = subprocess.run(cmd, capture_output=True, cwd=locus_dir)
    if result.returncode != 0:
        logger.error("FPocket failed for %s: %s", pdb_basename, result.stderr.decode(errors="replace")[:500])
        return None

    if not os.path.isdir(out_dir):
        stdout = result.stdout.decode(errors="replace")[:500]
        stderr = result.stderr.decode(errors="replace")[:500]
        logger.error("FPocket produced no output for %s. stdout=%s stderr=%s", pdb_basename, stdout, stderr)
        return None

    _docker_chmod_work_path(locus_dir, f"/work/{os.path.basename(out_dir)}")

    return out_dir


def _fpocket_to_json(fpocket_dir, python_bin=PYTHON_BIN):
    """Convert FPocket output dir to fpocket.json.gz. Returns path or None."""
    subprocess.run(["chmod", "-R", "a+rwX", fpocket_dir], capture_output=True)
    json_basename = f"{os.path.basename(fpocket_dir)}.json.gz"
    json_gz = os.path.join(os.path.dirname(fpocket_dir), json_basename)
    if os.path.exists(json_gz):
        return json_gz

    cmd = (
        "set -o pipefail; "
        f"{shlex.quote(python_bin)} -m SNDG.Structure.FPocket 2json {shlex.quote(fpocket_dir)} "
        f"| gzip > {shlex.quote(json_gz)}"
    )
    result = subprocess.run(["bash", "-lc", cmd], capture_output=True)
    if result.returncode != 0 or not os.path.exists(json_gz) or os.path.getsize(json_gz) == 0:
        logger.error("fpocket2json failed for %s: %s", fpocket_dir, result.stderr.decode(errors="replace")[:500])
        try:
            os.remove(json_gz)
        except OSError:
            pass
        return None

    try:
        with gzip.open(json_gz, "rt") as fh:
            json.load(fh)
    except Exception as exc:
        logger.error("fpocket2json produced invalid JSON for %s: %s", fpocket_dir, exc)
        try:
            os.remove(json_gz)
        except OSError:
            pass
        return None
    subprocess.run(["chmod", "a+rw", json_gz], capture_output=True)
    return json_gz


def _run_p2rank(locus_dir, pdb_path, cpus=2):
    """Run P2Rank via Docker. Returns path to output dir or None."""
    pdb_path = _tool_safe_pdb_path(locus_dir, pdb_path)
    pdb_basename = os.path.splitext(os.path.basename(pdb_path))[0]
    out_dir = os.path.join(locus_dir, f"{pdb_basename}_p2rank")
    predictions_csv = os.path.join(out_dir, f"{pdb_basename}_predictions.csv")
    p2json = os.path.join(out_dir, "p2pocket.json.gz")

    if os.path.exists(predictions_csv) or os.path.exists(p2json):
        logger.debug("P2Rank output already exists for %s", pdb_basename)
        return out_dir
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)

    os.makedirs(out_dir, exist_ok=True)
    pdb_basename_only = os.path.basename(pdb_path)
    out_rel = os.path.relpath(out_dir, locus_dir)

    cmd = [
        "docker", "run",
        "--rm", "-i",
        "-v", f"{_docker_mount_source(locus_dir)}:/work",
        "mcpalumbo/p2rank:latest",
        "prank", "predict",
        "-f", f"/work/{pdb_basename_only}",
        "-o", f"/work/{out_rel}",
        "-threads", str(cpus),
    ]
    logger.info("Running P2Rank for %s", pdb_basename)
    result = subprocess.run(cmd, capture_output=True, cwd=locus_dir)
    if result.returncode != 0:
        stdout = result.stdout.decode(errors="replace")[:1000]
        stderr = result.stderr.decode(errors="replace")[:1000]
        logger.error("P2Rank failed for %s. stdout=%s stderr=%s", pdb_basename, stdout, stderr)
        return None

    subprocess.run(["chmod", "-R", "a+rwX", out_dir], capture_output=True)

    return out_dir


def _p2rank_to_json(p2rank_dir, pdb_basename):
    """Convert P2Rank predictions CSV to p2pocket.json.gz. Returns path or None."""
    csv_path = os.path.join(p2rank_dir, f"{pdb_basename}_predictions.csv")
    if not os.path.exists(csv_path):
        candidates = [
            os.path.join(p2rank_dir, name)
            for name in os.listdir(p2rank_dir)
            if name.endswith("_predictions.csv")
        ]
        if len(candidates) == 1:
            csv_path = candidates[0]
    json_gz = os.path.join(p2rank_dir, "p2pocket.json.gz")

    if os.path.exists(json_gz):
        return json_gz

    if not os.path.exists(csv_path):
        logger.warning("P2Rank predictions CSV not found: %s", csv_path)
        # write empty so load_fpocket can skip gracefully
        with gzip.open(json_gz, "wt") as fh:
            json.dump([], fh)
        return json_gz

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        logger.error("Cannot read P2Rank CSV %s: %s", csv_path, exc)
        return None

    df.columns = [c.strip() for c in df.columns]
    data_list = []
    for _, row in df.iterrows():
        try:
            name = int(str(row["name"])[6:].replace(" ", ""))
            residues = str(row["residue_ids"]).replace("_", "").split()
            atoms = str(row["surf_atom_ids"]).split()
            data_list.append({
                "number": name,
                "residues": residues,
                "atoms": atoms,
                "properties": {
                    "P2Rank score": row["score"],
                    "P2Rrank probability": row["probability"],
                },
            })
        except Exception as exc:
            logger.warning("Skipping malformed P2Rank row: %s", exc)

    with gzip.open(json_gz, "wt") as fh:
        json.dump(data_list, fh)
    return json_gz


class Command(BaseCommand):
    help = (
        "Run FPocket + P2Rank + druggability on crystal (EX) structures "
        "that were loaded by backfill_experimental_structures."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "genomes",
            nargs="*",
            help="Genome accession(s) to process. Omit to run all.",
        )
        parser.add_argument(
            "--datadir",
            default=DEFAULT_DATA_DIR,
            help="Base data directory (default: %(default)s)",
        )
        parser.add_argument(
            "--cpus",
            type=int,
            default=2,
            help="Threads for P2Rank (default: 2)",
        )
        parser.add_argument(
            "--skip-fpocket",
            action="store_true",
            help="Skip FPocket step (useful if already run).",
        )
        parser.add_argument(
            "--skip-p2rank",
            action="store_true",
            help="Skip P2Rank step.",
        )
        parser.add_argument(
            "--skip-druggability",
            action="store_true",
            help="Skip druggability_2_csv step.",
        )

    def handle(self, *args, **options):
        datadir = options["datadir"].rstrip("/")
        cpus = options["cpus"]
        genomes_arg = options["genomes"]
        skip_fpocket = options["skip_fpocket"]
        skip_p2rank = options["skip_p2rank"]
        skip_druggability = options["skip_druggability"]

        qs = Biodatabase.objects.exclude(name__endswith=Biodatabase.PROT_POSTFIX)
        if genomes_arg:
            qs = qs.filter(name__in=genomes_arg)

        assemblies = list(qs.values_list("name", flat=True))
        if not assemblies:
            self.stdout.write("No matching genomes found.")
            return

        self.stdout.write(f"Processing {len(assemblies)} genome(s).")

        for assembly_name in assemblies:
            acclen = len(assembly_name)
            folder_name = assembly_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
            folder_path = f"{datadir}/{folder_name}/{assembly_name}"
            exp_dir = os.path.join(folder_path, "experimental")

            if not os.path.isdir(exp_dir):
                self.stdout.write(f"  [{assembly_name}] No experimental/ directory — skipping.")
                continue

            self.stdout.write(f"\n[{assembly_name}]")
            processed = skipped = 0

            # Find all EX PDB structures associated with proteins from this genome
            proteome_name = f"{assembly_name}{Biodatabase.PROT_POSTFIX}"
            links = (
                BioentryStructure.objects
                .select_related("pdb", "bioentry")
                .filter(
                    bioentry__biodatabase__name=proteome_name,
                    pdb__experiment="EX",
                )
            )

            for link in links:
                pdb_obj = link.pdb
                pdb_code = pdb_obj.code  # e.g. "7NU0"
                locus_tag = link.bioentry.accession

                locus_dir = os.path.join(exp_dir, locus_tag)
                pdb_path = os.path.join(locus_dir, f"{pdb_code}.pdb")

                if not os.path.isfile(pdb_path):
                    self.stdout.write(f"    {locus_tag}: PDB file missing ({pdb_path}) — skipping")
                    skipped += 1
                    continue

                self.stdout.write(f"    {locus_tag} / {pdb_code}")
                analysis_pdb_path = _filtered_pdb_for_chain(pdb_path, link.chain, locus_dir)
                if analysis_pdb_path != pdb_path:
                    self.stdout.write(f"      Using mapped chain(s): {link.chain}")

                # --- FPocket ---
                if not skip_fpocket:
                    fpocket_dir = _run_fpocket(locus_dir, analysis_pdb_path)
                    if fpocket_dir:
                        json_gz = _fpocket_to_json(fpocket_dir)
                        if json_gz:
                            try:
                                call_command(
                                    "load_fpocket",
                                    pdb_code,
                                    pocket_json=json_gz,
                                    datadir=datadir,
                                    verbosity=0,
                                )
                                self.stdout.write(f"      FPocket loaded")
                            except SystemExit as exc:
                                if exc.code != 0:
                                    self.stderr.write(f"      load_fpocket (FP) exited {exc.code}")
                            except Exception as exc:
                                self.stderr.write(f"      load_fpocket (FP) error: {exc}")
                        else:
                            self.stdout.write(f"      FPocket JSON conversion failed — skipping load")
                    else:
                        self.stdout.write(f"      FPocket run failed — skipping")

                # --- P2Rank ---
                if not skip_p2rank:
                    p2rank_dir = _run_p2rank(locus_dir, analysis_pdb_path, cpus=cpus)
                    if p2rank_dir:
                        pdb_basename = os.path.splitext(os.path.basename(analysis_pdb_path))[0]
                        p2json = _p2rank_to_json(p2rank_dir, pdb_basename)
                        if p2json:
                            try:
                                call_command(
                                    "load_fpocket",
                                    pdb_code,
                                    pocket_json=p2json,
                                    P2rank_pocket=True,
                                    datadir=datadir,
                                    verbosity=0,
                                )
                                self.stdout.write(f"      P2Rank loaded")
                            except SystemExit as exc:
                                if exc.code != 0:
                                    self.stderr.write(f"      load_fpocket (P2) exited {exc.code}")
                            except Exception as exc:
                                self.stderr.write(f"      load_fpocket (P2) error: {exc}")
                        else:
                            self.stdout.write(f"      P2Rank JSON failed — skipping load")
                    else:
                        self.stdout.write(f"      P2Rank run failed — skipping")

                processed += 1

            self.stdout.write(
                f"  Done: {processed} processed, {skipped} skipped."
            )

            # --- Druggability ---
            if not skip_druggability and processed > 0:
                self.stdout.write(f"  Running druggability_2_csv for {assembly_name}...")
                try:
                    call_command("druggability_2_csv", assembly_name, datadir=datadir, verbosity=0)
                    self.stdout.write(f"  Druggability done.")
                except SystemExit as exc:
                    if exc.code != 0:
                        self.stderr.write(f"  druggability_2_csv exited {exc.code}")
                except Exception as exc:
                    self.stderr.write(f"  druggability_2_csv error: {exc}")

"""
import_external_results — import pre-computed analysis results into TPW.

Currently supports the "gates" format: results TSV produced by the
Gates-Targets pipeline, optionally paired with a structures directory
extracted from the companion tar.gz archive.

Usage
-----
python manage.py import_external_results <genome_name> \\
    --results-tsv /path/to/KpATCC43816_results_table.tsv \\
    [--structures-dir /path/to/KpATCC43816/structures] \\
    [--datadir ./data] \\
    [--overwrite] \\
    [--dry-run]
"""

import math
import os
import shutil
import sys
import tempfile

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tqdm import tqdm

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.score_params import resolve_score_param_for_import
from tpweb.services.score_param_types import is_numeric_score_param


# ---------------------------------------------------------------------------
# Column mapping: Gates TSV column name → TPW ScoreParam name
# Only columns listed here are imported; the rest are silently skipped.
# ---------------------------------------------------------------------------

GATES_COLUMN_MAP = {
    # Categorical — exact-match TPW system params
    "human_offtarget": "human_offtarget",

    # Numeric — TPW system param created by Initialize_druggability()
    "druggability_score": "Druggability",

    # Categorical — TPW system param created by Initialize_celular_localization()
    "psortb_localization": "Localization",

    # Numeric custom params (auto-created if absent)
    "gut_microbiome_offtarget_norm": "gut_microbiome_offtarget_norm",
    "gut_microbiome_offtarget_counts": "gut_microbiome_offtarget_counts",
    "colabfold_plddt": "colabfold_plddt",

    # Categorical custom params
    "core_roary": "core_roary",
    "core_corecruncher": "core_corecruncher",
}

SUPPORTED_FORMATS = ("gates",)


class Command(BaseCommand):
    help = "Import pre-computed analysis results (scores + optionally structures) into TPW."

    def add_arguments(self, parser):
        parser.add_argument(
            "genome_name",
            help=(
                "Internal genome name as stored in TPW (e.g. 'public__KpATCC43816'). "
                "The genome must already be loaded in the database."
            ),
        )
        parser.add_argument(
            "--results-tsv",
            required=True,
            metavar="PATH",
            help="Path to the results TSV (tab-separated, must have a 'gene' column).",
        )
        parser.add_argument(
            "--structures-dir",
            default=None,
            metavar="PATH",
            help=(
                "Path to the extracted structures directory from the companion tar.gz. "
                "When provided, PDB files are copied into the TPW data directory so "
                "that structure-based analysis (load_af_model, fpocket, p2rank) can be "
                "run afterwards. Skipped if not given."
            ),
        )
        parser.add_argument(
            "--datadir",
            default="./data",
            metavar="PATH",
            help="TPW data directory (default: ./data).",
        )
        parser.add_argument(
            "--format",
            default="gates",
            choices=SUPPORTED_FORMATS,
            help="External pipeline format (default: gates).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing score values for this genome.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without writing to the database.",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        results_tsv = options["results_tsv"]
        structures_dir = options["structures_dir"]
        datadir = options["datadir"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        # --- Validate genome ---
        genome_qs = Biodatabase.objects.filter(name=genome_name + Biodatabase.PROT_POSTFIX)
        if not genome_qs.exists():
            raise CommandError(
                f"Genome '{genome_name}' not found in the database. "
                f"Load the GBK first before importing external results."
            )
        genome = genome_qs.get()

        # --- Validate input file ---
        if not os.path.isfile(results_tsv):
            raise CommandError(f"Results TSV not found: {results_tsv}")

        self.stdout.write(f"Reading {results_tsv} …")
        df = pd.read_csv(results_tsv, sep="\t", index_col=False, low_memory=False)

        if "gene" not in df.columns:
            raise CommandError("Results TSV must have a 'gene' column with locus tags.")

        # --- Apply column mapping ---
        col_map = GATES_COLUMN_MAP if options["format"] == "gates" else {}
        mapped = {"gene": df["gene"]}
        for src_col, tpw_col in col_map.items():
            if src_col in df.columns:
                mapped[tpw_col] = df[src_col]
            else:
                self.stderr.write(
                    self.style.WARNING(f"  Column '{src_col}' not found in TSV, skipping.")
                )
        mapped_df = pd.DataFrame(mapped)

        tpw_cols = [c for c in mapped_df.columns if c != "gene"]
        self.stdout.write(f"Columns to import: {', '.join(tpw_cols)}")

        if not tpw_cols:
            raise CommandError("No recognised columns found. Nothing to import.")

        # --- Write temp TSV and delegate to load_score_values logic ---
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[dry-run] Would import {len(mapped_df)} rows × "
                    f"{len(tpw_cols)} score columns into '{genome_name}'."
                )
            )
        else:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tsv", delete=False, encoding="utf-8"
            ) as tmp:
                mapped_df.to_csv(tmp, sep="\t", index=False)
                tmp_path = tmp.name

            try:
                self.stdout.write("Loading scores …")
                call_command(
                    "load_score_values",
                    genome_name,
                    tmp_path,
                    datadir=datadir,
                    overwrite=overwrite,
                )
            finally:
                os.unlink(tmp_path)

        # --- Copy structure files (optional) ---
        if structures_dir:
            self._copy_structures(
                genome_name=genome_name,
                structures_dir=structures_dir,
                datadir=datadir,
                dry_run=dry_run,
            )

        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------

    def _copy_structures(self, genome_name, structures_dir, datadir, dry_run):
        """
        Copy ColabFold PDB files from the Gates structures directory into
        the TPW alphafold directory expected by load_af_model / fpocket.

        Gates layout:  {structures_dir}/{locus_tag}/CB_{locus_tag}_relaxed1.pdb
        TPW layout:    {folder_path}/alphafold/{locus_tag}/{locus_tag}_af.pdb
        """
        if not os.path.isdir(structures_dir):
            self.stderr.write(
                self.style.WARNING(
                    f"Structures directory not found: {structures_dir}. Skipping."
                )
            )
            return

        folder_path = _compute_folder_path(datadir, genome_name)
        alphafold_dir = os.path.join(folder_path, "alphafold")

        locus_tags = sorted(
            d for d in os.listdir(structures_dir)
            if os.path.isdir(os.path.join(structures_dir, d))
        )
        if not locus_tags:
            self.stderr.write(
                self.style.WARNING("No protein subdirectories found in structures-dir.")
            )
            return

        self.stdout.write(
            f"Copying PDB files for {len(locus_tags)} proteins → {alphafold_dir}"
        )

        copied = skipped = missing = 0
        for locus_tag in tqdm(locus_tags, file=sys.stderr):
            src_pdb = os.path.join(
                structures_dir, locus_tag, f"CB_{locus_tag}_relaxed1.pdb"
            )
            if not os.path.isfile(src_pdb):
                missing += 1
                continue

            dest_dir = os.path.join(alphafold_dir, locus_tag)
            dest_pdb = os.path.join(dest_dir, f"{locus_tag}_af.pdb")

            if os.path.exists(dest_pdb) and not dry_run:
                skipped += 1
                continue

            if dry_run:
                copied += 1
                continue

            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src_pdb, dest_pdb)
            copied += 1

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefix}Structures: {copied} copied, {skipped} already present, {missing} no PDB found."
        )
        if not dry_run and copied:
            self.stdout.write(
                "PDB files are in place. Run load_af_model + fpocket/p2rank for each "
                "protein, then druggability_2_csv to regenerate the Druggability score.\n"
                "Or use the --load-structures flag (coming soon) to automate this."
            )


# ---------------------------------------------------------------------------

def _compute_folder_path(datadir, genome_name):
    """Mirror the path logic from run_pipeline_direct._compute_folder_path."""
    acclen = len(genome_name)
    folder_name = genome_name[math.floor(acclen / 2 - 1) : math.floor(acclen / 2 + 2)]
    return os.path.join(datadir, folder_name, genome_name)

"""
Predict structures with ColabFold for proteins that lack an AlphaFold model.

ColabFold uses the public MMseqs2 API for MSA generation (no GPU needed)
then runs AlphaFold2 inference locally on CPU.  Slower than ESMFold but
produces AF2-quality models and handles proteins of any size.

Usage:
    python manage.py colabfold_predict <genome> --datadir ../data

Requirements:
    colabfold_batch must be installed and on PATH, or its full path
    provided via the TPW_COLABFOLD_BIN env var (or --colabfold-bin arg).

    Install on cluster host (outside container):
        bash <(curl -s https://raw.githubusercontent.com/YoshitakaMo/localcolabfold/main/install_colabbatch_linux.sh)

    Or inside a conda env:
        conda install -c conda-forge -c bioconda colabfold
"""

import gzip
import math
import os
import shutil
import subprocess
import sys
import tempfile

from django.core.management.base import BaseCommand


DEFAULT_COLABFOLD_BIN = os.getenv("TPW_COLABFOLD_BIN", "colabfold_batch")
DEFAULT_NUM_RECYCLES = int(os.getenv("TPW_COLABFOLD_NUM_RECYCLES", "3"))
DEFAULT_NUM_MODELS = int(os.getenv("TPW_COLABFOLD_NUM_MODELS", "1"))


class Command(BaseCommand):
    help = "Predict structures with ColabFold for proteins without AlphaFold models."

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Genome accession (internal name)")
        parser.add_argument("--datadir", default="../data")
        parser.add_argument(
            "--colabfold-bin",
            default=DEFAULT_COLABFOLD_BIN,
            help="Path to colabfold_batch binary (default: %(default)s)",
        )
        parser.add_argument(
            "--num-recycles",
            type=int,
            default=DEFAULT_NUM_RECYCLES,
            help="Number of AlphaFold recycles — higher = more accurate but slower (default: %(default)s)",
        )
        parser.add_argument(
            "--num-models",
            type=int,
            default=DEFAULT_NUM_MODELS,
            help="Number of AlphaFold models to run per sequence (default: %(default)s)",
        )

    def handle(self, *args, **options):
        genome = options["genome"]
        datadir = options["datadir"]
        colabfold_bin = options["colabfold_bin"]
        num_recycles = options["num_recycles"]
        num_models = options["num_models"]

        # Resolve folder path (same convention as run_pipeline_direct.py)
        acclen = len(genome)
        folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
        folder_path = os.path.join(datadir, folder_name, genome)
        alphafold_dir = os.path.join(folder_path, "alphafold")

        # Read all protein sequences from FASTA
        faa_path = os.path.join(folder_path, f"{genome}.faa.gz")
        if not os.path.exists(faa_path):
            self.stderr.write(f"FASTA file not found: {faa_path}")
            return

        sequences = self._read_fasta(faa_path)
        self.stdout.write(f"Total proteins in FASTA: {len(sequences)}")

        # Find proteins that already have a structure PDB
        already_have = set()
        if os.path.isdir(alphafold_dir):
            for locus_tag in os.listdir(alphafold_dir):
                pdb_path = os.path.join(alphafold_dir, locus_tag, f"{locus_tag}_af.pdb")
                if os.path.exists(pdb_path) and os.path.getsize(pdb_path) > 0:
                    already_have.add(locus_tag)

        self.stdout.write(f"Proteins with existing structure: {len(already_have)}")

        # Candidates: everything without a structure — no size limit
        candidates = [
            (tag, seq)
            for tag, seq in sequences.items()
            if tag not in already_have
        ]

        self.stdout.write(f"Candidates for ColabFold: {len(candidates)}")

        if not candidates:
            self.stdout.write("Nothing to predict.")
            return

        # Run ColabFold in a temp directory then copy results
        with tempfile.TemporaryDirectory(prefix="colabfold_") as tmpdir:
            input_fasta = os.path.join(tmpdir, "input.fasta")
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir)

            # Write all candidates to a single FASTA (colabfold_batch handles batching)
            with open(input_fasta, "w") as fh:
                for locus_tag, seq in candidates:
                    fh.write(f">{locus_tag}\n{seq}\n")

            self.stdout.write(
                f"Running colabfold_batch: {len(candidates)} sequences, "
                f"{num_models} model(s), {num_recycles} recycle(s)…"
            )

            success = self._run_colabfold(
                colabfold_bin, input_fasta, output_dir,
                num_recycles, num_models,
            )

            if not success:
                self.stderr.write(
                    "colabfold_batch exited with an error. "
                    "Partial results (if any) will still be saved."
                )

            # Copy rank_001 PDB for each candidate into the expected location
            predicted = 0
            failed = 0
            for locus_tag, _ in candidates:
                pdb_src = self._find_best_pdb(output_dir, locus_tag)
                if pdb_src is None:
                    self.stderr.write(f"  No PDB produced for {locus_tag}")
                    failed += 1
                    continue

                locus_dir = os.path.join(alphafold_dir, locus_tag)
                os.makedirs(locus_dir, exist_ok=True)
                pdb_dst = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
                shutil.copy2(pdb_src, pdb_dst)
                self.stdout.write(f"  Saved structure: {locus_tag}")
                predicted += 1

        self.stdout.write(
            f"ColabFold done: {predicted} predicted, {failed} failed"
        )

    # ------------------------------------------------------------------

    def _read_fasta(self, faa_gz_path):
        """Read gzipped FASTA, return {locus_tag: sequence}."""
        sequences = {}
        current_tag = None
        current_seq = []

        with gzip.open(faa_gz_path, "rt") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(">"):
                    if current_tag and current_seq:
                        sequences[current_tag] = "".join(current_seq)
                    current_tag = line[1:].split()[0]
                    current_seq = []
                else:
                    current_seq.append(line)

        if current_tag and current_seq:
            sequences[current_tag] = "".join(current_seq)

        return sequences

    def _run_colabfold(self, colabfold_bin, input_fasta, output_dir,
                       num_recycles, num_models):
        """
        Invoke colabfold_batch and stream its stdout/stderr to our stdout.
        Returns True if exit code == 0.
        """
        cmd = [
            colabfold_bin,
            input_fasta,
            output_dir,
            "--num-recycle", str(num_recycles),
            "--num-models", str(num_models),
            # --use-gpu-relax is intentionally omitted: GPU relaxation unavailable on CPU-only
            "--model-type", "alphafold2_ptm",
        ]

        self.stdout.write("CMD: " + " ".join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            self.stdout.write(line.rstrip())
            sys.stdout.flush()

        proc.wait()
        return proc.returncode == 0

    def _find_best_pdb(self, output_dir, locus_tag):
        """
        ColabFold names outputs like:
          {locus_tag}_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb
        Return the path to the rank_001 PDB for this locus_tag, or None.
        """
        try:
            candidates = [
                f for f in os.listdir(output_dir)
                if f.startswith(locus_tag + "_")
                and "rank_001" in f
                and f.endswith(".pdb")
            ]
        except FileNotFoundError:
            return None

        if not candidates:
            return None

        # Prefer unrelaxed (relaxed won't exist without GPU anyway)
        candidates.sort()
        return os.path.join(output_dir, candidates[0])

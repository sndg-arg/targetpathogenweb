"""
Predict structures with ESMFold for proteins that lack an AlphaFold model.

Usage:
    python manage.py esmfold_predict <genome> --datadir /app/targetpathogenweb/data
"""

import gzip
import math
import os
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


ESMFOLD_API_URL = os.getenv(
    "TPW_ESMFOLD_API_URL",
    "https://api.esmatlas.com/foldSequence/v1/pdb/",
)
DEFAULT_MAX_LENGTH = int(os.getenv("TPW_ESMFOLD_MAX_LENGTH", "400"))
DEFAULT_DELAY = float(os.getenv("TPW_ESMFOLD_DELAY_SEC", "1"))
DEFAULT_TIMEOUT = int(os.getenv("TPW_ESMFOLD_TIMEOUT_SEC", "120"))
MAX_RETRIES = 3
DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")


class Command(BaseCommand):
    help = "Predict structures with ESMFold for proteins without AlphaFold models."

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Genome accession (internal name)")
        parser.add_argument("--datadir", default=DEFAULT_DATA_DIR)
        parser.add_argument(
            "--max-length",
            type=int,
            default=DEFAULT_MAX_LENGTH,
            help="Max sequence length to send to ESMFold (default: %(default)s)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=DEFAULT_DELAY,
            help="Seconds between API calls (default: %(default)s)",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_TIMEOUT,
            help="HTTP timeout per request in seconds (default: %(default)s)",
        )

    def handle(self, *args, **options):
        genome = options["genome"]
        datadir = options["datadir"]
        max_length = options["max_length"]
        delay = options["delay"]
        timeout = options["timeout"]

        # Resolve folder path (same convention as run_pipeline.py)
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

        # Determine candidates
        candidates = []
        skipped_long = 0
        for locus_tag, seq in sequences.items():
            if locus_tag in already_have:
                continue
            if len(seq) > max_length:
                skipped_long += 1
                continue
            candidates.append((locus_tag, seq))

        self.stdout.write(
            f"Candidates for ESMFold: {len(candidates)} "
            f"(skipped {skipped_long} sequences > {max_length} residues)"
        )

        if not candidates:
            self.stdout.write("Nothing to predict.")
            return

        predicted = 0
        failed = 0

        for i, (locus_tag, seq) in enumerate(candidates, 1):
            self.stdout.write(f"[{i}/{len(candidates)}] Predicting {locus_tag} ({len(seq)} aa)...")

            pdb_text = self._call_esmfold(seq, timeout)
            if pdb_text is None:
                self.stderr.write(f"  FAILED: {locus_tag}")
                failed += 1
                continue

            # Save in the same layout alphafold_unips uses
            locus_dir = os.path.join(alphafold_dir, locus_tag)
            os.makedirs(locus_dir, exist_ok=True)
            pdb_path = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
            with open(pdb_path, "w") as fh:
                fh.write(pdb_text)

            predicted += 1

            if i < len(candidates):
                time.sleep(delay)

        self.stdout.write(
            f"ESMFold done: {predicted} predicted, {failed} failed, "
            f"{skipped_long} skipped (too long)"
        )

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

    def _call_esmfold(self, sequence, timeout):
        """Call ESMFold API, return PDB text or None on failure."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    ESMFOLD_API_URL,
                    data=sequence,
                    timeout=timeout,
                    headers={"Content-Type": "text/plain"},
                )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5))
                    self.stderr.write(f"  Rate-limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES:
                    self.stderr.write(f"  Attempt {attempt} failed: {exc}")
                    time.sleep(2 * attempt)
                else:
                    self.stderr.write(f"  All {MAX_RETRIES} attempts failed: {exc}")
        return None

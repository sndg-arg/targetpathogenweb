"""Predict ColabFold models on SLURM for reviewed human proteins with no model.

Reuses stage 16's remote runner (`pipeline/colabfold_remote.py`) over a work
folder holding `human_colabfold.faa.gz`, so SLURM submission, GPU->CPU
fallback, SSH-outage retries and recovery of an interrupted run's outputs all
behave exactly as for genomes. Resumable: proteins already linked to an AF/CF
model are not selected, and a model already copied back is not predicted again.

Selenocysteine (U) is sent as cysteine (C): neither AlphaFold DB nor ColabFold
models it. A returned model is imported only when its residues match that
sequence exactly; the protein page says Sec was modeled as Cys.

Usage (as root, which owns data/ and has the cluster SSH config mounted):
    python manage.py predict_human_colabfold [--accession P07203 ...] [--dry-run]
"""

import configparser
import gzip
import os
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from human_target.services.human_targets import human_proteins_queryset
from tpweb.management.commands.load_verified_colabfold_model import model_sequence
from tpweb.models.BioentryStructure import BioentryStructure

WORK_NAME = "human_colabfold"
STANDARD = set("ACDEFGHIKLMNPQRSTVWY")


def colabfold_sequence(sequence):
    return sequence.replace("U", "C")


def select_candidates(rows, min_length, max_length):
    """(selected, skipped): skipped carries a reason per accession."""
    selected, skipped = [], []
    for accession, sequence in rows:
        query = colabfold_sequence(sequence)
        if len(query) < min_length:
            skipped.append((accession, f"shorter than {min_length} aa"))
        elif len(query) > max_length:
            skipped.append((accession, f"longer than {max_length} aa"))
        elif not set(query) <= STANDARD:
            skipped.append((accession, "non-standard residues besides U"))
        else:
            selected.append((accession, query))
    return selected, skipped


class Command(BaseCommand):
    help = "Predict and import ColabFold models for reviewed human proteins without one."

    def add_arguments(self, parser):
        parser.add_argument("--accession", action="append", default=[])
        parser.add_argument("--datadir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--min-length", type=int, default=30)
        parser.add_argument("--max-length", type=int, default=2500)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        proteins = human_proteins_queryset().filter(is_reviewed=True)
        if options["accession"]:
            proteins = proteins.filter(uniprot_accession__in=options["accession"])
        modeled = BioentryStructure.objects.filter(
            pdb__experiment__in=("AF", "CF"), pdb__deprecated=False
        ).values("bioentry_id")
        rows = list(
            proteins.exclude(bioentry_id__in=modeled)
            .order_by("uniprot_accession")
            .values_list("uniprot_accession", "sequence")
        )
        selected, skipped = select_candidates(rows, options["min_length"], options["max_length"])
        for accession, reason in skipped:
            self.stdout.write(f"skip {accession}: {reason}")
        self.stdout.write(f"{len(selected)} proteins to predict: {[a for a, _ in selected]}")
        if options["dry_run"] or not selected:
            return

        workdir = Path(options["datadir"]) / WORK_NAME
        workdir.mkdir(parents=True, exist_ok=True)
        with gzip.open(workdir / f"{WORK_NAME}.faa.gz", "wt") as handle:
            for accession, query in selected:
                handle.write(f">{accession}\n{query}\n")

        # Identical-copy reuse is about bacterial curated strains; never applies here.
        os.environ["TPW_REUSE_IDENTICAL_EVIDENCE"] = "0"
        pipeline_dir = str(settings.BASE_DIR / "pipeline")
        if pipeline_dir not in sys.path:
            sys.path.insert(0, pipeline_dir)
        from colabfold_remote import run_remote_colabfold

        cfg = configparser.ConfigParser()
        cfg.read(Path(pipeline_dir) / "settings.ini")
        run_error = None
        try:
            run_remote_colabfold(cfg, str(workdir), WORK_NAME)
        except RuntimeError as exc:
            # Some proteins failed; still import every model that came back.
            run_error = exc

        loaded, problems = 0, []
        for accession, query in selected:
            pdb_path = workdir / "alphafold" / accession / f"{accession}_af.pdb"
            if not pdb_path.is_file():
                problems.append(f"{accession}: no model returned")
                continue
            try:
                if model_sequence(pdb_path) != query:
                    problems.append(f"{accession}: model sequence differs, not imported")
                    continue
                call_command(
                    "load_af_model",
                    f"CF_{accession}",
                    str(pdb_path),
                    accession,
                    experiment="CF",
                    datadir=options["datadir"],
                )
            except SystemExit:
                pass  # load_af_model exits when the model is already loaded
            except CommandError as exc:
                problems.append(f"{accession}: {exc}")
                continue
            if BioentryStructure.objects.filter(
                bioentry__accession=accession, pdb__code=f"CF_{accession}"
            ).exists():
                loaded += 1
            else:
                problems.append(f"{accession}: not linked after import")

        for problem in problems:
            self.stderr.write(problem)
        self.stdout.write(f"ColabFold: loaded={loaded} of {len(selected)}")
        if run_error or problems:
            raise CommandError(f"Incomplete: {run_error or 'see problems above'}")

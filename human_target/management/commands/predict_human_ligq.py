"""Run LigQ_2 on SLURM for human proteins (reviewed, or all with --include-unreviewed)
and load the ligands into Binders.

Reuses stage 24's remote runner (`pipeline/ligq_remote.run_ligq_job`), one SLURM
job per chunk of proteins so a failure costs one chunk, not the proteome, and
local/remote disk stays bounded: once a chunk is loaded its output is deleted
on both sides and a LOADED marker is written.

Resumable: chunk membership is fixed the first time an accession is assigned
(data/human_ligq/chunk_NNN/proteins.fasta); later runs only add new accessions
as new chunks and process every chunk without a LOADED marker.

Selenocysteine (U) is sent as cysteine (C), as for ColabFold.

Usage (as root, which owns data/ and has the cluster SSH config mounted):
    python manage.py predict_human_ligq [--accession P07203 ...] [--chunk-size 1000]
        [--max-chunks N] [--keep-output] [--include-unreviewed] [--dry-run]
"""

import configparser
import shutil
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from human_target.management.commands.predict_human_colabfold import colabfold_sequence
from human_target.services.human_targets import human_proteins_queryset

WORK_NAME = "human_ligq"
FETCHED_MARKER = "FETCHED"
LOADED_MARKER = "LOADED"


def fasta_accessions(path):
    with open(path, encoding="utf-8") as handle:
        return [line[1:].split()[0] for line in handle if line.startswith(">")]


def plan_new_chunks(rows, assigned, chunk_size, excluded=()):
    """Unassigned (accession, sequence) rows split into chunks of chunk_size."""
    skip = set(assigned) | set(excluded)
    pending = [(acc, colabfold_sequence(seq)) for acc, seq in rows if acc not in skip and seq]
    return [pending[i : i + chunk_size] for i in range(0, len(pending), chunk_size)]


class Command(BaseCommand):
    help = "Run LigQ_2 on SLURM for reviewed human proteins and load the ligands."

    def add_arguments(self, parser):
        parser.add_argument("--accession", action="append", default=[])
        parser.add_argument(
            "--include-unreviewed",
            action="store_true",
            help="Also TrEMBL entries (new chunks after the reviewed ones).",
        )
        parser.add_argument("--datadir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--chunk-size", type=int, default=1000)
        parser.add_argument("--max-chunks", type=int, default=0, help="0 = all pending chunks")
        parser.add_argument("--keep-output", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        pipeline_dir = str(settings.BASE_DIR / "pipeline")
        if pipeline_dir not in sys.path:
            sys.path.insert(0, pipeline_dir)
        from ligq_remote import _build_ligq_config, run_ligq_job

        cfg = configparser.ConfigParser()
        cfg.read(Path(pipeline_dir) / "settings.ini")
        config = _build_ligq_config(cfg)

        workdir = Path(options["datadir"]) / WORK_NAME
        chunk_dirs = sorted(workdir.glob("chunk_*")) if workdir.is_dir() else []
        assigned = [acc for d in chunk_dirs for acc in fasta_accessions(d / "proteins.fasta")]

        proteins = human_proteins_queryset()
        if not options["include_unreviewed"]:
            proteins = proteins.filter(is_reviewed=True)
        if options["accession"]:
            proteins = proteins.filter(uniprot_accession__in=options["accession"])
        rows = proteins.order_by("uniprot_accession").values_list("uniprot_accession", "sequence")
        new_chunks = plan_new_chunks(rows, assigned, options["chunk_size"], config.exclude_loci)

        pending = [d for d in chunk_dirs if not (d / LOADED_MARKER).exists()]
        self.stdout.write(
            f"{len(assigned)} proteins already in {len(chunk_dirs)} chunks "
            f"({len(chunk_dirs) - len(pending)} loaded); "
            f"{sum(map(len, new_chunks))} new proteins in {len(new_chunks)} new chunks"
        )
        if options["dry_run"]:
            return

        next_index = len(chunk_dirs)
        for offset, chunk in enumerate(new_chunks):
            chunk_dir = workdir / f"chunk_{next_index + offset:03d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            with open(chunk_dir / "proteins.fasta", "w", encoding="utf-8") as handle:
                for accession, sequence in chunk:
                    handle.write(f">{accession}\n{sequence}\n")
            pending.append(chunk_dir)
        if options["max_chunks"]:
            pending = pending[: options["max_chunks"]]

        for index, chunk_dir in enumerate(pending, start=1):
            self.stdout.write(f"[{index}/{len(pending)}] {chunk_dir.name}")
            output_dir = chunk_dir / "output"
            if not (chunk_dir / FETCHED_MARKER).exists():
                shutil.rmtree(output_dir, ignore_errors=True)  # partial copy of a failed run
                try:
                    run_ligq_job(
                        config,
                        str(chunk_dir / "proteins.fasta"),
                        str(chunk_dir),
                        f"{WORK_NAME}_{chunk_dir.name}",
                        remove_remote=True,
                    )
                except (RuntimeError, TimeoutError) as exc:
                    raise CommandError(f"{chunk_dir.name}: {exc}") from exc
                (chunk_dir / FETCHED_MARKER).touch()
            call_command(
                "load_ligq_2_results",
                str(output_dir),
                max_known_per_protein=config.max_known_per_protein,
                max_zinc_per_protein=config.max_zinc_per_protein,
                min_tanimoto=config.min_tanimoto,
            )
            (chunk_dir / LOADED_MARKER).touch()
            if not options["keep_output"]:
                shutil.rmtree(output_dir)

        if pending:
            call_command("refresh_human_target_summary")

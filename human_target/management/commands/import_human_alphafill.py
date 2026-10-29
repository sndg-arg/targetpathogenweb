"""Transfer precomputed AlphaFill models from the login node, then ingest them."""

import configparser
import json
import shlex
import sys
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from human_target.services.alphafill_transfer import (
    REMOTE_INVENTORY,
    stage_file,
    validate_model_path,
)
from human_target.services.human_targets import human_proteins_queryset


class Command(BaseCommand):
    help = "Resume transfer and sequential import of already-computed human AlphaFill models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remote-dir", default="/storage/home/agutson/human_proteome_raw/alphafill"
        )
        parser.add_argument("--datadir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--accession", action="append", default=[])
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        proteins = human_proteins_queryset()
        if options["accession"]:
            proteins = proteins.filter(uniprot_accession__in=options["accession"])
        requested = set(proteins.values_list("uniprot_accession", flat=True))
        if not requested:
            raise CommandError("No matching human proteins found.")

        pipeline_dir = str(settings.BASE_DIR / "pipeline")
        if pipeline_dir not in sys.path:
            sys.path.insert(0, pipeline_dir)
        from ligq_remote import _build_ligq_config
        from slurm_remote_command import (
            _close_remote_session,
            _exec_remote,
            _open_remote_session,
        )

        cfg = configparser.ConfigParser()
        cfg.read(Path(pipeline_dir) / "settings.ini")
        config = _build_ligq_config(cfg)
        remote_root = PurePosixPath(options["remote_dir"])
        local_root = Path(options["datadir"]) / "human_alphafill"
        ssh, scp, sftp = _open_remote_session(config)
        try:
            self.stdout.write("Reading AlphaFill inventory on the login node...")
            python = config.conda_env.rstrip("/") + "/bin/python"
            code, out, err = _exec_remote(
                ssh, shlex.join([python, "-c", REMOTE_INVENTORY, str(remote_root)])
            )
            if code:
                raise CommandError(f"Remote AlphaFill inventory failed: {err}")
            inventory = json.loads(out)
            rows = [row for row in inventory["models"] if row[0] in requested]
            if not rows:
                raise CommandError("No AlphaFill models available for the selected proteins.")
            for accession, relative, size, metadata_size in rows:
                validate_model_path(accession, relative)
                if size <= 0 or (metadata_size is not None and metadata_size <= 0):
                    raise CommandError(f"Empty AlphaFill source file for {accession}.")
            self.stdout.write(
                f"AlphaFill: {len(rows)} models available; "
                f"{len(requested) - len(rows)} selected proteins without a model; "
                f"{sum(row[3] is None for row in rows)} without metadata."
            )
            if options["dry_run"]:
                return
            stage_file(
                sftp,
                str(remote_root / "LICENSE.txt"),
                local_root / "LICENSE.txt",
                inventory["license_size"],
            )
            downloaded = reused = 0
            for index, (_accession, relative, size, metadata_size) in enumerate(rows, 1):
                files = [(PurePosixPath(relative), size)]
                if metadata_size is not None:
                    files.append((PurePosixPath(relative).with_suffix(".json"), metadata_size))
                for path, expected_size in files:
                    if stage_file(
                        sftp, str(remote_root / path), local_root / str(path), expected_size
                    ):
                        downloaded += 1
                    else:
                        reused += 1
                if index % 250 == 0 or index == len(rows):
                    self.stdout.write(
                        f"AlphaFill transfer: {index}/{len(rows)} models; "
                        f"{downloaded} files copied, {reused} reused."
                    )
        except (OSError, ValueError) as exc:
            raise CommandError(f"AlphaFill transfer failed: {exc}") from exc
        finally:
            _close_remote_session(ssh, scp, sftp)

        call_command(
            "load_human_structures_bulk",
            skip_alphafold=True,
            skip_experimental=True,
            alphafill_dir=str(local_root),
            accession=options["accession"],
            datadir=options["datadir"],
        )
        call_command("refresh_human_target_summary")
        self.stdout.write(self.style.SUCCESS("AlphaFill import and summary refresh completed."))

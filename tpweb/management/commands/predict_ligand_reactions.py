"""Find synthesis routes for every known ligand (PDB and ChEMBL) on SLURM.

Exports the distinct ligand SMILES, runs scripts/cluster/match_ligand_reactions.py
in one SLURM job (RDKit from the LigQ_2 conda env) against USPTO-50K and
PaRoutes, copies the matches back and loads them with load_ligand_reactions.
The datasets live on the cluster (/storage, see docs/context/FEATURES.md).

Usage (as root, which owns data/ and has the cluster SSH config mounted):
    python manage.py predict_ligand_reactions [--dry-run] [--load-only]
"""

import configparser
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from tpweb.models.Binders import Binders

DATASETS = "/storage/home/agutson/reaction_datasets"
WORK_NAME = "ligand_reactions"
ENV_PREFIX = "TPW_REACTIONS"


def export_ligand_smiles(path):
    """Distinct PDB/ChEMBL ligand SMILES, one per line; returns the count."""
    smiles = (
        Binders.objects.filter(source__in=(Binders.SOURCE_PDB, Binders.SOURCE_CHEMBL))
        .exclude(smiles="")
        .values_list("smiles", flat=True)
        .distinct()
    )
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for value in smiles.iterator(chunk_size=5000):
            value = value.strip()
            if value and "\n" not in value:
                handle.write(value + "\n")
                count += 1
    return count


class Command(BaseCommand):
    help = "Match known ligands to USPTO-50K / PaRoutes reactions on SLURM and load them."

    def add_arguments(self, parser):
        parser.add_argument("--datadir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--uspto50k", default=f"{DATASETS}/uspto50k/data_processed.csv")
        parser.add_argument(
            "--paroutes", default=f"{DATASETS}/paroutes2/selected_reactions_all.csv"
        )
        parser.add_argument("--dry-run", action="store_true", help="Export the ligands only.")
        parser.add_argument(
            "--load-only", action="store_true", help="Load the last routes.tsv.gz again."
        )

    def handle(self, *args, **options):
        workdir = Path(options["datadir"]) / WORK_NAME
        workdir.mkdir(parents=True, exist_ok=True)
        local_routes = workdir / "routes.tsv.gz"
        if options["load_only"]:
            call_command("load_ligand_reactions", str(local_routes))
            return

        local_ligands = workdir / "ligands.txt"
        count = export_ligand_smiles(local_ligands)
        self.stdout.write(f"{count} distinct ligand SMILES exported to {local_ligands}")
        if options["dry_run"] or not count:
            return

        pipeline_dir = str(settings.BASE_DIR / "pipeline")
        if pipeline_dir not in sys.path:
            sys.path.insert(0, pipeline_dir)
        from ligq_remote import _build_ligq_config
        from slurm_remote_command import (
            _build_config,
            _close_remote_session,
            _exec_remote,
            _open_remote_session,
            run_remote_shell_job,
        )

        os.environ.setdefault(f"{ENV_PREFIX}_SLURM_CPUS", "12")
        os.environ.setdefault(f"{ENV_PREFIX}_SLURM_MEM", "48G")
        cfg = configparser.ConfigParser()
        cfg.read(Path(pipeline_dir) / "settings.ini")
        config = _build_config(cfg, ENV_PREFIX)
        conda = _build_ligq_config(cfg)

        run = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        remote_dir = f"{config.ssh_rootfolder.rstrip('/')}/tpw_reactions/{run}"
        remote_script = f"{remote_dir}/match_ligand_reactions.py"
        remote_ligands = f"{remote_dir}/ligands.txt"
        remote_routes = f"{remote_dir}/routes.tsv.gz"

        ssh, scp_client, sftp = _open_remote_session(config)
        try:
            code, _out, err = _exec_remote(ssh, f"mkdir -p {shlex.quote(remote_dir)}")
            if code != 0:
                raise CommandError(f"Cannot create {remote_dir}: {err}")
            scp_client.put(str(local_ligands), remote_ligands)
            scp_client.put(
                str(settings.BASE_DIR / "scripts" / "cluster" / "match_ligand_reactions.py"),
                remote_script,
            )
        finally:
            _close_remote_session(ssh, scp_client, sftp)

        # The env's own python, no `conda activate`: some nodes (nodo1) don't
        # mount /home/shared, where the base conda lives.
        python = f"{conda.conda_env.rstrip('/')}/bin/python"
        command = (
            f"{shlex.quote(python)} {shlex.quote(remote_script)} "
            f"--ligands {shlex.quote(remote_ligands)} "
            f"--uspto50k {shlex.quote(options['uspto50k'])} "
            f"--paroutes {shlex.quote(options['paroutes'])} "
            f'--out {shlex.quote(remote_routes)} --workers "$SLURM_CPUS_PER_TASK"'
        )
        try:
            run_remote_shell_job(cfg, env_prefix=ENV_PREFIX, job_name=WORK_NAME, command=command)
        except (RuntimeError, TimeoutError) as exc:
            raise CommandError(str(exc)) from exc

        ssh, scp_client, sftp = _open_remote_session(config)
        try:
            scp_client.get(remote_routes, str(local_routes))
        finally:
            _close_remote_session(ssh, scp_client, sftp)
        self.stdout.write(f"Routes copied to {local_routes} (remote run kept in {remote_dir})")
        call_command("load_ligand_reactions", str(local_routes))

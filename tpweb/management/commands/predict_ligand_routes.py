"""Build a multi-step synthesis plan for every known ligand, on SLURM.

Same shape as predict_ligand_reactions (which finds single reactions): exports
the distinct ligand SMILES, runs scripts/cluster/expand_ligand_routes.py in one
SLURM job against USPTO-50K and PaRoutes, copies the plans back and loads them
with load_ligand_routes. match_ligand_reactions.py travels along, because the
expander imports its SMILES handling.

Usage (in the queue container, the only one with the cluster SSH config mounted):
    python manage.py predict_ligand_routes [--dry-run] [--load-only]
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

from tpweb.management.commands.predict_ligand_reactions import DATASETS, export_ligand_smiles

WORK_NAME = "ligand_routes"
ENV_PREFIX = "TPW_ROUTES"
SCRIPTS = ("expand_ligand_routes.py", "match_ligand_reactions.py")


class Command(BaseCommand):
    help = "Build multi-step synthesis plans for known ligands on SLURM and load them."

    def add_arguments(self, parser):
        parser.add_argument("--datadir", default=str(settings.BASE_DIR / "data"))
        parser.add_argument("--uspto50k", default=f"{DATASETS}/uspto50k/data_processed.csv")
        parser.add_argument(
            "--paroutes", default=f"{DATASETS}/paroutes2/selected_reactions_all.csv"
        )
        parser.add_argument("--max-depth", type=int, default=3)
        parser.add_argument("--dry-run", action="store_true", help="Export the ligands only.")
        parser.add_argument(
            "--load-only", action="store_true", help="Load the last plans.jsonl.gz again."
        )

    def handle(self, *args, **options):
        workdir = Path(options["datadir"]) / WORK_NAME
        workdir.mkdir(parents=True, exist_ok=True)
        local_plans = workdir / "plans.jsonl.gz"
        if options["load_only"]:
            call_command("load_ligand_routes", str(local_plans))
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
        remote_dir = f"{config.ssh_rootfolder.rstrip('/')}/tpw_routes/{run}"
        remote_ligands = f"{remote_dir}/ligands.txt"
        remote_plans = f"{remote_dir}/plans.jsonl.gz"

        ssh, scp_client, sftp = _open_remote_session(config)
        try:
            code, _out, err = _exec_remote(ssh, f"mkdir -p {shlex.quote(remote_dir)}")
            if code != 0:
                raise CommandError(f"Cannot create {remote_dir}: {err}")
            scp_client.put(str(local_ligands), remote_ligands)
            for name in SCRIPTS:
                scp_client.put(
                    str(settings.BASE_DIR / "scripts" / "cluster" / name), f"{remote_dir}/{name}"
                )
        finally:
            _close_remote_session(ssh, scp_client, sftp)

        # The env's own python, no `conda activate`: some nodes (nodo1) don't
        # mount /home/shared, where the base conda lives.
        python = f"{conda.conda_env.rstrip('/')}/bin/python"
        command = (
            f"cd {shlex.quote(remote_dir)} && "
            f"{shlex.quote(python)} {shlex.quote(f'{remote_dir}/expand_ligand_routes.py')} "
            f"--ligands {shlex.quote(remote_ligands)} "
            f"--uspto50k {shlex.quote(options['uspto50k'])} "
            f"--paroutes {shlex.quote(options['paroutes'])} "
            f"--max-depth {int(options['max_depth'])} "
            f'--out {shlex.quote(remote_plans)} --workers "$SLURM_CPUS_PER_TASK"'
        )
        try:
            run_remote_shell_job(cfg, env_prefix=ENV_PREFIX, job_name=WORK_NAME, command=command)
        except (RuntimeError, TimeoutError) as exc:
            raise CommandError(str(exc)) from exc

        ssh, scp_client, sftp = _open_remote_session(config)
        try:
            scp_client.get(remote_plans, str(local_plans))
        finally:
            _close_remote_session(ssh, scp_client, sftp)
        self.stdout.write(f"Plans copied to {local_plans} (remote run kept in {remote_dir})")
        call_command("load_ligand_routes", str(local_plans))

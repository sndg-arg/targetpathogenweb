"""
Run FastTarget's off-target/essentiality searches on a remote SLURM CPU node
via SSH, instead of locally on Nodo0 (a shared orchestration node, not a
bioinformatics compute node -- see docs/CLUSTER_DEPLOY.md).

Unlike InterProScan/ColabFold/LigQ_2, the tool FastTarget needs isn't
installed on the cluster: FastTarget itself only wraps plain `blastp`
(human off-target, DEG essentiality) and `diamond blastp` (gut microbiome
off-target) -- see fasttarget/ftscripts/offtargets.py and essentiality.py.
No Docker/Singularity container is involved in this path (fasttarget.py's
container_engine option is only used by unrelated optional features --
foldseek/roary/psortb/corecruncher -- that Target's own fast_command.py
never enables).

Analogous to ligq_remote.py: one SLURM job per genome, both the BLAST/DIAMOND
search AND fasttarget's own result parsing (ftscripts.offtargets/essentiality)
run remotely, since the parsing needs the microbiome species catalogue
(counting total genomes analyzed) that only exists on the cluster's storage,
not on Nodo0. Only the final small TSVs are copied back.

Activated when TPW_FASTTARGET_USE_REMOTE=1; otherwise stage 4 runs fasttarget.py
locally (blocked by the heavy-stage guard on Nodo0 unless --allow-local-heavy
is passed explicitly).

Flow:
  1. Dump genome FASTA from the DB, unzip the stored GBK if needed.
  2. SCP both + an sbatch script to the cluster.
  3. Submit a single SLURM job that runs the BLAST/DIAMOND searches and
     fasttarget's own parsing (ftscripts.offtargets/essentiality), writing
     human_offtarget.tsv, hit_in_deg.tsv, gut_microbiome_offtarget_counts.tsv.
  4. Poll until COMPLETED / FAILED / TIMEOUT.
  5. Pull the offtarget/ and essentiality/ output folders back as a tar stream.
  6. Run fast_command locally with TPW_FASTTARGET_SKIP_EXEC=1 and
     TPW_FASTTARGET_ORGANISM_DIR pointed at the copied-back output -- reuses
     fast_command.py's existing DB-loading logic unchanged, it never re-runs
     fasttarget.py itself.
"""

import gzip
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

from slurm_remote_command import (
    REMOTE_FAILURE_PREFIXES,
    _assert_ssh_reachable,
    _close_remote_session,
    _config_text,
    _env_int,
    _env_text,
    _exec_remote,
    _open_remote_session,
    _resolve_ssh_options,
)

# fasttarget's own config.py defaults (fast_command.py never overrides these).
MICROBIOME_IDENTITY_FILTER = 40
MICROBIOME_COVERAGE_FILTER = 70
DEG_IDENTITY_FILTER = 40
DEG_COVERAGE_FILTER = 70


def _record_event(run_id_raw, *, status, message, payload=None):
    if not run_id_raw or not message:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id_raw),
            stage_number=4,
            app_name="fasttarget_remote",
            status=status,
            message=message,
            payload=dict(payload or {}),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class FastTargetRemoteConfig:
    ssh_rootfolder: str
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_password: str | None
    ssh_key_filename: str | list[str] | None
    ssh_connect_timeout: int
    remote_poll_seconds: int
    remote_wait_seconds: int
    conda_prefix: str
    conda_env: str
    fasttarget_dir: str
    databases_dir: str
    slurm_partition: str
    slurm_time: str
    slurm_mem: str
    slurm_cpus_per_task: int
    slurm_exclude: str


def _build_fasttarget_config(cfg_dict):
    ssh_connect_timeout = _env_int("TPW_FASTTARGET_SSH_CONNECT_TIMEOUT_SEC", default=10)
    ssh_port = _env_int("SSH_PORT", default=22)
    ssh_rootfolder = _env_text("SSH_WORKDIR") or _config_text(cfg_dict, "SSH", "WorkingDir")
    ssh_host = _env_text("SSH_HOSTNAME") or _config_text(cfg_dict, "SSH", "HostName")
    ssh_user = _env_text("SSH_USERNAME") or _config_text(cfg_dict, "SSH", "Username")

    ssh_options = _resolve_ssh_options(ssh_host, user=ssh_user, port=ssh_port)
    ssh_host = ssh_options["host"]
    ssh_user = ssh_options["user"]
    ssh_port = ssh_options["port"]
    env_key_filename = _env_text("SSH_KEY_FILENAME")
    ssh_key_filename = (
        os.path.expanduser(env_key_filename) if env_key_filename else ssh_options["key_filename"]
    )

    ssh_password = _env_text("SSH_PASSWORD")
    if ssh_password is None:
        ssh_password = _config_text(cfg_dict, "SSH", "Password")

    missing = []
    if not ssh_rootfolder:
        missing.append("SSH_WORKDIR")
    if not ssh_host:
        missing.append("SSH_HOSTNAME")
    if not ssh_user:
        missing.append("SSH_USERNAME")
    if missing:
        raise RuntimeError(
            f"FastTarget remote configuration is incomplete. Set {', '.join(missing)} "
            f"via environment or pipeline/settings.ini."
        )

    return FastTargetRemoteConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_password=ssh_password,
        ssh_key_filename=ssh_key_filename,
        ssh_connect_timeout=ssh_connect_timeout,
        remote_poll_seconds=_env_int("TPW_FASTTARGET_REMOTE_POLL_SEC", default=30),
        remote_wait_seconds=_env_int("TPW_FASTTARGET_REMOTE_WAIT_SEC", default=21600),
        conda_prefix=_env_text("TPW_FASTTARGET_CONDA_PREFIX", default="/home/shared/miniconda3.8"),
        conda_env=_env_text("TPW_FASTTARGET_CONDA_ENV", default="fasttarget"),
        fasttarget_dir=_env_text("TPW_FASTTARGET_REMOTE_DIR", default="/home/agutson/fasttarget"),
        databases_dir=_env_text(
            "TPW_FASTTARGET_REMOTE_DATABASES_DIR", default="/home/agutson/fasttarget_databases"
        ),
        slurm_partition=_env_text("TPW_FASTTARGET_SLURM_PARTITION", default="cpu"),
        slurm_time=_env_text("TPW_FASTTARGET_SLURM_TIME", default="02:00:00"),
        slurm_mem=_env_text("TPW_FASTTARGET_SLURM_MEM", default="8G"),
        slurm_cpus_per_task=_env_int("TPW_FASTTARGET_SLURM_CPUS", default=4),
        slurm_exclude=os.getenv("TPW_FASTTARGET_SLURM_EXCLUDE", "").strip(),
    )


def _ensure_local_gbk(folder_path, genome):
    """fast_command.py does the same gz-on-demand unzip -- mirrored here so
    the remote job gets a real .gbk file to parse locus tags from."""
    gbk_path = os.path.join(folder_path, f"{genome}.gbk")
    gbk_path_gz = os.path.join(folder_path, f"{genome}.gbk.gz")
    if not os.path.exists(gbk_path):
        with gzip.open(gbk_path_gz, "rb") as f_in, open(gbk_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    return gbk_path


# ---------------------------------------------------------------------------
# SBATCH script
# ---------------------------------------------------------------------------


def _build_slurm_script(config, *, genome, remote_workdir):
    remote_script = f"""
import os
import sys
sys.path.insert(0, {config.fasttarget_dir!r})
from ftscripts import offtargets, essentiality

databases_path = {config.databases_dir!r}
output_path = {remote_workdir!r}
organism_name = {genome!r}
cpus = {config.slurm_cpus_per_task}

# human_offtarget_blast/essential_deg_blast write straight into these dirs
# without creating them first (unlike microbiome_offtarget_blast_species,
# which does) -- fasttarget.py's own CLI normally creates them earlier in
# its pipeline, which this bypasses by calling these functions directly.
os.makedirs(os.path.join(output_path, organism_name, "offtarget"), exist_ok=True)
os.makedirs(os.path.join(output_path, organism_name, "essentiality"), exist_ok=True)

offtargets.human_offtarget_blast(databases_path, output_path, organism_name, cpus=cpus)
offtargets.microbiome_offtarget_blast_species(databases_path, output_path, organism_name, cpus=cpus)
essentiality.essential_deg_blast(databases_path, output_path, organism_name, cpus=cpus)

offtargets.human_offtarget_parse(output_path, organism_name)
offtargets.microbiome_species_parse(
    databases_path, output_path, organism_name, {MICROBIOME_IDENTITY_FILTER}, {MICROBIOME_COVERAGE_FILTER}
)
essentiality.deg_parse(output_path, organism_name, {DEG_IDENTITY_FILTER}, {DEG_COVERAGE_FILTER})
print("fasttarget_remote: search + parse complete")
""".strip("\n")

    return "\n".join(
        [
            "#!/bin/bash",
            "#SBATCH --job-name=fasttarget",
            f"#SBATCH -p {config.slurm_partition}",
            *((f"#SBATCH --exclude={config.slurm_exclude}",) if config.slurm_exclude else ()),
            f"#SBATCH --cpus-per-task={config.slurm_cpus_per_task}",
            f"#SBATCH --time={config.slurm_time}",
            f"#SBATCH --mem={config.slurm_mem}",
            f"#SBATCH -o {remote_workdir}/slurm-%j.out",
            f"#SBATCH -e {remote_workdir}/slurm-%j.err",
            f"#SBATCH --chdir={remote_workdir}",
            "",
            "set -euo pipefail",
            f'source "{config.conda_prefix}/etc/profile.d/conda.sh"',
            f'conda activate "{config.conda_env}"',
            "cat <<'PYEOF' > run_fasttarget.py",
            remote_script,
            "PYEOF",
            "python run_fasttarget.py",
            f'touch "{remote_workdir}/DONE"',
            "",
        ]
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_remote_fasttarget(cfg_dict, folder_path, genome, working_dir):
    """Run FastTarget's off-target/essentiality searches for a whole genome
    on the cluster, then load results into Target via the local fast_command
    (skip_exec + organism-dir-override -- no re-run of fasttarget.py)."""
    from bioseq.models.Biodatabase import Biodatabase
    from django.core.management import call_command

    config = _build_fasttarget_config(cfg_dict)
    run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()

    biodb_name = f"{genome}{Biodatabase.PROT_POSTFIX}"

    local_ft_dir = os.path.join(folder_path, "fasttarget_remote")
    local_fasta = os.path.join(local_ft_dir, f"{genome}.faa")
    local_output_dir = os.path.join(local_ft_dir, "output")
    os.makedirs(local_ft_dir, exist_ok=True)

    print(f"FastTarget remote: dumping FASTA for {biodb_name} -> {local_fasta}")
    call_command("dump_genome_proteins_fasta", biodb_name, output=local_fasta)
    local_gbk = _ensure_local_gbk(folder_path, genome)

    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    safe_genome = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in genome)
    run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    remote_workdir = f"{config.ssh_rootfolder.rstrip('/')}/tpw_fasttarget/{safe_genome}_{run_label}"
    remote_genome_dir = f"{remote_workdir}/{genome}/genome"
    remote_fasta = f"{remote_genome_dir}/{genome}.faa"
    remote_gbk = f"{remote_genome_dir}/{genome}.gbk"
    remote_slurm = f"{remote_workdir}/fasttarget.slurm"
    remote_done = f"{remote_workdir}/DONE"
    remote_tar = f"{remote_workdir}/output.tar.gz"

    ssh, scp_client, sftp = _open_remote_session(config)
    job_id = None
    finished = False
    try:
        mk_exit, _, mk_err = _exec_remote(ssh, f"mkdir -p {shlex.quote(remote_genome_dir)}")
        if mk_exit != 0:
            raise RuntimeError(f"Cannot create remote dir {remote_genome_dir}: {mk_err}")

        scp_client.put(local_fasta, remote_fasta)
        scp_client.put(local_gbk, remote_gbk)

        slurm_text = _build_slurm_script(config, genome=genome, remote_workdir=remote_workdir)
        with sftp.file(remote_slurm, "w") as handle:
            handle.write(slurm_text)

        sub_exit, sub_out, sub_err = _exec_remote(
            ssh,
            f"cd {shlex.quote(remote_workdir)} && sbatch --parsable {shlex.quote(remote_slurm)}",
        )
        if sub_exit != 0:
            raise RuntimeError(f"sbatch failed: {sub_err or sub_out}")
        job_id = sub_out.split(";")[0].strip()
        if not job_id:
            raise RuntimeError(f"Cannot parse FastTarget SLURM job id from: {sub_out!r}")

        print(f"FastTarget remote: submitted SLURM job {job_id}")
        _record_event(
            run_id_raw,
            status="info",
            message=f"Submitted remote FastTarget job {job_id} for {genome}",
            payload={"job_id": job_id, "remote_workdir": remote_workdir, "genome": genome},
        )

        waited = 0
        last_state = "PENDING"
        while not finished and waited <= config.remote_wait_seconds:
            done_exit, _, _ = _exec_remote(ssh, f"test -f {shlex.quote(remote_done)}")
            if done_exit == 0:
                finished = True
                break

            _, state_out, _ = _exec_remote(
                ssh,
                f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n | head -n 1",
            )
            line = state_out.splitlines()[0].strip() if state_out else ""
            parts = line.split("|") if line else []
            if len(parts) >= 3:
                _, state, exit_code = parts[:3]
                last_state = state or last_state
                up = state.upper()
                if up.startswith(REMOTE_FAILURE_PREFIXES):
                    _, slurm_out, _ = _exec_remote(
                        ssh,
                        f"tail -n 120 {shlex.quote(remote_workdir)}/slurm-{job_id}.out 2>/dev/null || true",
                    )
                    _, slurm_err, _ = _exec_remote(
                        ssh,
                        f"tail -n 120 {shlex.quote(remote_workdir)}/slurm-{job_id}.err 2>/dev/null || true",
                    )
                    raise RuntimeError(
                        f"Remote FastTarget failed ({state} / {exit_code}): "
                        f"{slurm_err or slurm_out or 'no remote output'}"
                    )

            print(f"FastTarget remote: waiting (state={last_state}, {waited}s elapsed)")
            time.sleep(config.remote_poll_seconds)
            waited += config.remote_poll_seconds

        if not finished:
            raise TimeoutError(f"FastTarget did not finish in {waited}s (last state: {last_state})")

        print("FastTarget remote: pulling offtarget/essentiality output via tar stream")
        os.makedirs(local_output_dir, exist_ok=True)
        local_tar = os.path.join(local_ft_dir, f"fasttarget_output_{run_label}.tar.gz")

        tar_exit, _, tar_err = _exec_remote(
            ssh,
            f"tar czf {shlex.quote(remote_tar)} -C {shlex.quote(remote_workdir + '/' + genome)} "
            "offtarget essentiality",
        )
        if tar_exit != 0:
            raise RuntimeError(f"Remote tar failed: {tar_err}")
        scp_client.get(remote_tar, local_tar)
        subprocess.run(["tar", "xzf", local_tar, "-C", local_output_dir], check=True)
        os.remove(local_tar)
        _exec_remote(ssh, f"rm -f {shlex.quote(remote_tar)}")

        print(
            "FastTarget remote: loading results via fast_command (skip_exec + organism-dir override)"
        )
        previous_skip_exec = os.environ.get("TPW_FASTTARGET_SKIP_EXEC")
        previous_organism_dir = os.environ.get("TPW_FASTTARGET_ORGANISM_DIR")
        os.environ["TPW_FASTTARGET_SKIP_EXEC"] = "1"
        os.environ["TPW_FASTTARGET_ORGANISM_DIR"] = local_output_dir
        try:
            call_command(
                "fast_command", genome, folder_path, datadir=os.path.join(working_dir, "data")
            )
        finally:
            if previous_skip_exec is None:
                os.environ.pop("TPW_FASTTARGET_SKIP_EXEC", None)
            else:
                os.environ["TPW_FASTTARGET_SKIP_EXEC"] = previous_skip_exec
            if previous_organism_dir is None:
                os.environ.pop("TPW_FASTTARGET_ORGANISM_DIR", None)
            else:
                os.environ["TPW_FASTTARGET_ORGANISM_DIR"] = previous_organism_dir

        _record_event(
            run_id_raw,
            status="info",
            message=f"FastTarget stage complete (job {job_id})",
            payload={"job_id": job_id, "genome": genome},
        )
    finally:
        if not finished and job_id:
            try:
                _exec_remote(ssh, f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"FastTarget remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
        _close_remote_session(ssh, scp_client, sftp)

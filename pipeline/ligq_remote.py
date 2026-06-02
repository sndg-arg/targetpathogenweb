"""
Run LigQ_2 on a remote SLURM CPU node via SSH.

Analogous to interproscan_remote.py / colabfold_remote.py but simpler:
LigQ_2 takes a multi-protein FASTA and processes every protein internally,
so one SLURM job per genome is enough — no per-protein orchestration.

Activated when TPW_LIGQ_USE_REMOTE=1; otherwise stage 24 is skipped.

Flow:
  1. Dump genome FASTA from the DB.
  2. SCP FASTA + sbatch script to the cluster.
  3. Submit a single SLURM job.
  4. Poll until COMPLETED / FAILED / TIMEOUT.
  5. Pull output back as a tar stream (LigQ_2 produces thousands of small files).
  6. Load results into Binders via load_ligq_2_results.
"""

import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

import paramiko
from scp import SCPClient


REMOTE_FAILURE_PREFIXES = (
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
)

LIGQ_EXCLUDED_LOCI_REPORT = "excluded_loci.tsv"


def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_text(name, default=None):
    raw = os.getenv(name)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _env_float(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _config_text(cfg_dict, section, option, default=None):
    try:
        value = cfg_dict.get(section, option, fallback=None)
    except Exception:
        value = None
    text = str(value or "").strip()
    return text or default


def _resolve_ssh_options(host, user=None, port=22):
    resolved = {"host": host, "user": user, "port": port, "key_filename": None}
    config_path = os.path.expanduser("~/.ssh/config")
    if not os.path.exists(config_path):
        return resolved
    try:
        ssh_config = paramiko.SSHConfig()
        with open(config_path, "r", encoding="utf-8") as handle:
            ssh_config.parse(handle)
        entry = ssh_config.lookup(host)
    except Exception:
        return resolved
    resolved["host"] = entry.get("hostname") or resolved["host"]
    resolved["user"] = user or entry.get("user") or resolved["user"]
    entry_port = entry.get("port")
    if entry_port:
        try:
            resolved["port"] = int(entry_port)
        except (TypeError, ValueError):
            pass
    identity_files = entry.get("identityfile") or []
    if identity_files:
        expanded = [os.path.expanduser(p) for p in identity_files]
        resolved["key_filename"] = expanded if len(expanded) > 1 else expanded[0]
    return resolved


def _assert_ssh_reachable(host, port, timeout):
    probe = socket.socket()
    probe.settimeout(timeout)
    try:
        probe.connect((host, int(port or 22)))
    finally:
        probe.close()


def _record_event(run_id_raw, *, stage_number, status, message, payload=None):
    if not run_id_raw or not message:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id_raw),
            stage_number=stage_number,
            app_name="ligq_remote",
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
class LigqRemoteConfig:
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
    ligq_dir: str
    ligq_data_dir: str
    slurm_partition: str
    slurm_time: str
    slurm_mem: str
    slurm_cpus_per_task: int
    slurm_exclude: str
    max_known_per_protein: int
    max_zinc_per_protein: int
    min_tanimoto: float
    exclude_loci: tuple[str, ...]


def _build_ligq_config(cfg_dict):
    ssh_connect_timeout = _env_int("TPW_LIGQ_SSH_CONNECT_TIMEOUT_SEC", default=10)
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
        os.path.expanduser(env_key_filename)
        if env_key_filename
        else ssh_options["key_filename"]
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
            f"LigQ_2 remote configuration is incomplete. Set {', '.join(missing)} "
            f"via environment or pipeline/settings.ini."
        )

    return LigqRemoteConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_password=ssh_password,
        ssh_key_filename=ssh_key_filename,
        ssh_connect_timeout=ssh_connect_timeout,
        remote_poll_seconds=_env_int("TPW_LIGQ_REMOTE_POLL_SEC", default=60),
        remote_wait_seconds=_env_int("TPW_LIGQ_REMOTE_WAIT_SEC", default=172800),
        conda_prefix=_env_text("TPW_LIGQ_CONDA_PREFIX", default="/home/shared/miniconda3.8"),
        conda_env=_env_text(
            "TPW_LIGQ_CONDA_ENV",
            default="/home/agutson/work/conda_envs/ligq_2_local",
        ),
        ligq_dir=_env_text("TPW_LIGQ_DIR", default="/home/agutson/work/LigQ_2"),
        ligq_data_dir=_env_text("TPW_LIGQ_DATA_DIR", default="/home/agutson/work/ligq_data"),
        slurm_partition=_env_text("TPW_LIGQ_SLURM_PARTITION", default="cpu"),
        slurm_time=_env_text("TPW_LIGQ_SLURM_TIME", default="48:00:00"),
        slurm_mem=_env_text("TPW_LIGQ_SLURM_MEM", default="32G"),
        slurm_cpus_per_task=_env_int("TPW_LIGQ_SLURM_CPUS", default=8),
        slurm_exclude=os.getenv("TPW_LIGQ_SLURM_EXCLUDE", "").strip(),
        max_known_per_protein=_env_int("TPW_LIGQ_MAX_KNOWN", default=100),
        max_zinc_per_protein=_env_int("TPW_LIGQ_MAX_ZINC", default=50),
        min_tanimoto=_env_float("TPW_LIGQ_MIN_TANIMOTO", default=0.5),
        exclude_loci=tuple(
            locus.strip()
            for locus in _env_text("TPW_LIGQ_EXCLUDE_LOCI", default="").split(",")
            if locus.strip()
        ),
    )


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------


def _open_remote_session(config):
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
    ssh.connect(
        config.ssh_host,
        port=config.ssh_port,
        username=config.ssh_user,
        password=config.ssh_password,
        timeout=config.ssh_connect_timeout,
        banner_timeout=config.ssh_connect_timeout,
        auth_timeout=config.ssh_connect_timeout,
        allow_agent=True,
        look_for_keys=True,
        key_filename=config.ssh_key_filename,
    )
    scp_client = SCPClient(ssh.get_transport())
    sftp = ssh.open_sftp()
    return ssh, scp_client, sftp


def _close_remote_session(ssh, scp_client, sftp):
    for handle in (scp_client, sftp, ssh):
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def _exec_remote(ssh, cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def _filter_fasta_loci(path, excluded_loci):
    if not excluded_loci:
        return []

    excluded = set(excluded_loci)
    tmp_path = f"{path}.tmp"
    skipped = []
    keep = True

    with open(path, encoding="utf-8") as src, open(tmp_path, "w", encoding="utf-8") as dst:
        for line in src:
            if line.startswith(">"):
                locus = line[1:].strip().split()[0]
                keep = locus not in excluded
                if not keep:
                    skipped.append(locus)
                    continue
            if keep:
                dst.write(line)

    os.replace(tmp_path, path)
    return skipped


def _write_excluded_loci_report(local_ligq_dir, skipped_loci):
    if not skipped_loci:
        return

    report_path = os.path.join(local_ligq_dir, LIGQ_EXCLUDED_LOCI_REPORT)
    note = (
        "Excluded from LigQ_2 FASTA only because HMMER/Pfam aborted with a numeric "
        "error for this protein; the protein remains available in TPW for other evidence."
    )
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write("locus\treason\tnote\n")
        for locus in skipped_loci:
            handle.write(f"{locus}\thmmer_forward_score_nan\t{note}\n")


# ---------------------------------------------------------------------------
# SBATCH script
# ---------------------------------------------------------------------------


def _build_slurm_script(config, remote_input, remote_output_dir, remote_workdir):
    return "\n".join([
        "#!/bin/bash",
        "#SBATCH --job-name=ligq2",
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
        f'mkdir -p "{remote_output_dir}"',
        'WORKDIR="$(mktemp -d -p /tmp ligq2_run.XXXXXX)"',
        'trap "rm -rf ${WORKDIR}" EXIT',
        'cd "${WORKDIR}"',
        f'ln -s "{config.ligq_data_dir}" databases',
        'echo "[$(date)] starting LigQ_2"',
        (
            f'python "{config.ligq_dir}/run_ligq_2.py" '
            f'--input-fasta "{remote_input}" '
            f'--output-dir "{remote_output_dir}"'
        ),
        'echo "[$(date)] LigQ_2 done"',
        f'touch "{remote_workdir}/DONE"',
        "",
    ])


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_remote_ligq(cfg_dict, folder_path, genome):
    """Run LigQ_2 for a whole genome on the cluster and load results into Binders."""
    from bioseq.models.Biodatabase import Biodatabase
    from django.core.management import call_command

    config = _build_ligq_config(cfg_dict)
    run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()

    biodb_name = f"{genome}{Biodatabase.PROT_POSTFIX}"

    local_ligq_dir = os.path.join(folder_path, "ligq2")
    local_fasta = os.path.join(local_ligq_dir, "proteins.fasta")
    local_output_dir = os.path.join(local_ligq_dir, "output")
    os.makedirs(local_ligq_dir, exist_ok=True)

    print(f"LigQ_2 remote: dumping FASTA for {biodb_name} → {local_fasta}")
    call_command("dump_genome_proteins_fasta", biodb_name, output=local_fasta)
    skipped_loci = _filter_fasta_loci(local_fasta, config.exclude_loci)
    if skipped_loci:
        _write_excluded_loci_report(local_ligq_dir, skipped_loci)
        print(
            "LigQ_2 remote: excluded "
            f"{len(skipped_loci)} problematic loci from FASTA: "
            f"{', '.join(skipped_loci)}"
        )

    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    safe_genome = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in genome)
    run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    remote_workdir = (
        f"{config.ssh_rootfolder.rstrip('/')}/tpw_ligq/{safe_genome}_{run_label}"
    )
    remote_input = f"{remote_workdir}/proteins.fasta"
    remote_output_dir = f"{remote_workdir}/output"
    remote_slurm = f"{remote_workdir}/ligq_batch.slurm"
    remote_done = f"{remote_workdir}/DONE"
    remote_tar = f"{remote_workdir}/output.tar.gz"

    ssh, scp_client, sftp = _open_remote_session(config)
    job_id = None
    finished = False
    try:
        mk_exit, _, mk_err = _exec_remote(ssh, f"mkdir -p {shlex.quote(remote_workdir)}")
        if mk_exit != 0:
            raise RuntimeError(f"Cannot create remote dir {remote_workdir}: {mk_err}")

        scp_client.put(local_fasta, remote_input)

        slurm_text = _build_slurm_script(
            config, remote_input, remote_output_dir, remote_workdir
        )
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
            raise RuntimeError(f"Cannot parse LigQ_2 SLURM job id from: {sub_out!r}")

        print(f"LigQ_2 remote: submitted SLURM job {job_id}")
        _record_event(
            run_id_raw,
            stage_number=24,
            status="info",
            message=f"Submitted remote LigQ_2 job {job_id} for {genome}",
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
                        f"Remote LigQ_2 failed ({state} / {exit_code}): "
                        f"{slurm_err or slurm_out or 'no remote output'}"
                    )

            print(f"LigQ_2 remote: waiting (state={last_state}, {waited}s elapsed)")
            time.sleep(config.remote_poll_seconds)
            waited += config.remote_poll_seconds

        if not finished:
            raise TimeoutError(
                f"LigQ_2 did not finish in {waited}s (last state: {last_state})"
            )

        print("LigQ_2 remote: pulling output via tar stream")
        os.makedirs(local_output_dir, exist_ok=True)
        local_tar = os.path.join(local_ligq_dir, f"ligq_output_{run_label}.tar.gz")

        tar_exit, _, tar_err = _exec_remote(
            ssh,
            f"tar czf {shlex.quote(remote_tar)} -C {shlex.quote(remote_workdir)} output",
        )
        if tar_exit != 0:
            raise RuntimeError(f"Remote tar failed: {tar_err}")
        scp_client.get(remote_tar, local_tar)
        subprocess.run(
            ["tar", "xzf", local_tar, "-C", local_ligq_dir],
            check=True,
        )
        os.remove(local_tar)
        _exec_remote(ssh, f"rm -f {shlex.quote(remote_tar)}")

        print("LigQ_2 remote: loading results into DB")
        call_command(
            "load_ligq_2_results",
            local_output_dir,
            max_known_per_protein=config.max_known_per_protein,
            max_zinc_per_protein=config.max_zinc_per_protein,
            min_tanimoto=config.min_tanimoto,
        )

        _record_event(
            run_id_raw,
            stage_number=24,
            status="info",
            message=f"LigQ_2 stage complete (job {job_id})",
            payload={"job_id": job_id, "genome": genome},
        )
    finally:
        if not finished and job_id:
            try:
                _exec_remote(ssh, f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"LigQ_2 remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
        _close_remote_session(ssh, scp_client, sftp)

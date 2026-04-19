"""
Run ColabFold on a remote SLURM GPU node via SSH.

Analogous to interproscan_remote.py: SSH → SCP input → sbatch → poll → SCP results.
Activated when TPW_COLABFOLD_USE_REMOTE=1 is set; otherwise stage 16 runs locally.

The remote job:
  1. Receives a FASTA with all candidate proteins (no existing AlphaFold structure).
  2. Runs colabfold_batch on a GPU node via SLURM.
  3. Produces one PDB per protein (rank_001).
  4. Results are SCP'd back and placed into alphafold/<locus_tag>/<locus_tag>_af.pdb.
"""

import gzip
import math
import os
import shlex
import shutil
import socket
import time
from dataclasses import dataclass
from datetime import datetime

import paramiko
from scp import SCPClient

from tpweb.services.slurm_messages import classify_slurm_resource_message


REMOTE_FAILURE_PREFIXES = (
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
)


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


def _assert_ssh_reachable(host, port, timeout_seconds):
    probe = socket.socket()
    probe.settimeout(timeout_seconds)
    try:
        probe.connect((host, int(port or 22)))
    finally:
        probe.close()


def _resolve_ssh_options(host, user=None, port=22):
    resolved = {
        "host": host,
        "user": user,
        "port": port,
        "key_filename": None,
    }
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
        expanded = [os.path.expanduser(path) for path in identity_files]
        resolved["key_filename"] = expanded if len(expanded) > 1 else expanded[0]

    return resolved


def _record_remote_job(run_id_raw, *, job_id, remote_job_dir):
    """Persist the SLURM job_id and remote_job_dir in PipelineRun for operability."""
    if not run_id_raw:
        return
    try:
        from tpweb.services.pipeline_runs import record_interproscan_remote_job

        record_interproscan_remote_job(
            int(run_id_raw),
            job_id=job_id,
            remote_job_dir=remote_job_dir,
        )
    except Exception:
        pass


def _record_remote_info(run_id_raw, *, stage_number, message, payload=None):
    if not run_id_raw or not message:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id_raw),
            stage_number=stage_number,
            app_name="colabfold_remote",
            status="info",
            message=message,
            payload=dict(payload or {}),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ColabFoldRemoteConfig:
    ssh_rootfolder: str
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_password: str | None
    ssh_key_filename: str | list[str] | None
    ssh_connect_timeout: int
    remote_poll_seconds: int
    remote_wait_seconds: int
    remote_completion_grace_seconds: int
    conda_prefix: str
    conda_env: str
    num_recycles: int
    num_models: int
    slurm_partition: str
    slurm_time: str
    slurm_mem: str
    slurm_gres: str


def _build_colabfold_config(cfg_dict):
    ssh_connect_timeout = _env_int("TPW_COLABFOLD_SSH_CONNECT_TIMEOUT_SEC", default=10)
    ssh_port = _env_int("SSH_PORT", default=22)
    ssh_rootfolder = _env_text("SSH_WORKDIR") or _config_text(cfg_dict, "SSH", "WorkingDir")
    ssh_host = _env_text("SSH_HOSTNAME") or _config_text(cfg_dict, "SSH", "HostName")
    ssh_user = _env_text("SSH_USERNAME") or _config_text(cfg_dict, "SSH", "Username")
    ssh_options = _resolve_ssh_options(ssh_host, user=ssh_user, port=ssh_port)
    ssh_host = ssh_options["host"]
    ssh_user = ssh_options["user"]
    ssh_port = ssh_options["port"]
    ssh_key_filename = ssh_options["key_filename"]

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
            f"ColabFold remote configuration is incomplete. Set {', '.join(missing)} "
            f"via environment or pipeline/settings.ini."
        )

    return ColabFoldRemoteConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_password=ssh_password,
        ssh_key_filename=ssh_key_filename,
        ssh_connect_timeout=ssh_connect_timeout,
        remote_poll_seconds=_env_int("TPW_COLABFOLD_REMOTE_POLL_SEC", default=60),
        remote_wait_seconds=_env_int("TPW_COLABFOLD_REMOTE_WAIT_SEC", default=43200),
        remote_completion_grace_seconds=_env_int(
            "TPW_COLABFOLD_REMOTE_COMPLETION_GRACE_SEC", default=120,
        ),
        conda_prefix=_env_text("TPW_COLABFOLD_CONDA_PREFIX", default="/home/shared/miniconda3.8"),
        conda_env=_env_text("TPW_COLABFOLD_CONDA_ENV", default="colabfold"),
        num_recycles=_env_int("TPW_COLABFOLD_NUM_RECYCLES", default=3),
        num_models=_env_int("TPW_COLABFOLD_NUM_MODELS", default=1),
        slurm_partition=os.getenv("TPW_COLABFOLD_PARTITION", "gpu"),
        slurm_time=os.getenv("TPW_COLABFOLD_TIME", "12:00:00"),
        slurm_mem=os.getenv("TPW_COLABFOLD_MEM", "16gb"),
        slurm_gres=os.getenv("TPW_COLABFOLD_GRES", "gpu:1"),
    )


def _config_text(cfg_dict, section, option, default=None):
    try:
        value = cfg_dict.get(section, option, fallback=None)
    except Exception:
        value = None
    text = str(value or "").strip()
    return text or default


# ---------------------------------------------------------------------------
# FASTA helpers
# ---------------------------------------------------------------------------

def _read_fasta_gz(faa_gz_path):
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


def _find_candidates(folder_path, genome):
    """Return list of (locus_tag, sequence) for proteins without an existing PDB."""
    faa_path = os.path.join(folder_path, f"{genome}.faa.gz")
    if not os.path.exists(faa_path):
        raise FileNotFoundError(f"FASTA file not found: {faa_path}")

    sequences = _read_fasta_gz(faa_path)
    alphafold_dir = os.path.join(folder_path, "alphafold")

    already_have = set()
    if os.path.isdir(alphafold_dir):
        for locus_tag in os.listdir(alphafold_dir):
            pdb_path = os.path.join(alphafold_dir, locus_tag, f"{locus_tag}_af.pdb")
            if os.path.exists(pdb_path) and os.path.getsize(pdb_path) > 0:
                already_have.add(locus_tag)

    return [
        (tag, seq) for tag, seq in sequences.items()
        if tag not in already_have
    ]


def _find_best_pdb(directory, locus_tag):
    """Find the rank_001 PDB produced by colabfold_batch for a locus_tag."""
    try:
        candidates = [
            f for f in os.listdir(directory)
            if f.startswith(locus_tag + "_")
            and "rank_001" in f
            and f.endswith(".pdb")
        ]
    except FileNotFoundError:
        return None
    if not candidates:
        return None
    candidates.sort()
    return os.path.join(directory, candidates[0])


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_remote_colabfold(cfg_dict, folder_path, genome):
    """
    Run ColabFold on a remote SLURM GPU node.

    1. Build a FASTA of proteins that don't have structures yet.
    2. SSH to the cluster, SCP the FASTA.
    3. Submit a SLURM job to the GPU partition.
    4. Poll until complete.
    5. SCP results back, place PDBs in alphafold/<locus_tag>/<locus_tag>_af.pdb.

    Returns the number of predicted structures.
    """
    candidates = _find_candidates(folder_path, genome)
    if not candidates:
        print("ColabFold remote: no candidates to predict.")
        return 0

    print(f"ColabFold remote: {len(candidates)} proteins to predict on GPU.")

    config = _build_colabfold_config(cfg_dict)
    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    # Write candidate FASTA to a local temp file
    import tempfile
    local_tmpdir = tempfile.mkdtemp(prefix="colabfold_remote_")
    local_input_fasta = os.path.join(local_tmpdir, "input.fasta")
    with open(local_input_fasta, "w") as fh:
        for locus_tag, seq in candidates:
            fh.write(f">{locus_tag}\n{seq}\n")

    ssh = None
    scp_client = None
    sftp = None
    job_id = None
    finished = False
    try:
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

        def _run_remote(command):
            stdin, stdout, stderr = ssh.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return exit_code, out, err

        scp_client = SCPClient(ssh.get_transport())
        sftp = ssh.open_sftp()

        run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
        remote_job_dir = (
            f"{config.ssh_rootfolder.rstrip('/')}/tpw_colabfold/{safe_genome}_{run_label}"
        )
        remote_input = f"{remote_job_dir}/input.fasta"
        remote_output_dir = f"{remote_job_dir}/output"
        remote_script = f"{remote_job_dir}/run_colabfold.sh"
        remote_slurm = f"{remote_job_dir}/colabfold.slurm"
        remote_done_marker = f"{remote_job_dir}/DONE"
        remote_stdout_pattern = f"{remote_job_dir}/slurm-%j.out"
        remote_stderr_pattern = f"{remote_job_dir}/slurm-%j.err"

        # Create remote directory and upload input
        mkdir_exit, _, mkdir_err = _run_remote(f"mkdir -p {shlex.quote(remote_job_dir)}")
        if mkdir_exit != 0:
            raise RuntimeError(
                f"Unable to create remote ColabFold directory: {mkdir_err or f'exit {mkdir_exit}'}"
            )

        scp_client.put(local_input_fasta, remote_input)

        # Build the runner script
        runner_text = "\n".join([
            "#!/bin/bash",
            "set -eo pipefail",
            f'eval "$({config.conda_prefix}/bin/conda shell.bash hook)"',
            f"conda activate {shlex.quote(config.conda_env)}",
            "set -u",
            f"mkdir -p {shlex.quote(remote_output_dir)}",
            (
                f"colabfold_batch"
                f" {shlex.quote(remote_input)}"
                f" {shlex.quote(remote_output_dir)}"
                f" --num-recycle {config.num_recycles}"
                f" --num-models {config.num_models}"
                f" --model-type alphafold2_ptm"
            ),
            f"touch {shlex.quote(remote_done_marker)}",
            "",
        ])

        # Build the SLURM submission script
        slurm_text = "\n".join([
            "#!/bin/bash",
            f"#SBATCH --job-name=cf_{safe_genome[:20]}",
            f"#SBATCH -p {config.slurm_partition}",
            f"#SBATCH --gres={config.slurm_gres}",
            f"#SBATCH --cpus-per-task=4",
            f"#SBATCH --time={config.slurm_time}",
            f"#SBATCH --mem={config.slurm_mem}",
            f"#SBATCH -o {remote_stdout_pattern}",
            f"#SBATCH -e {remote_stderr_pattern}",
            f"#SBATCH --chdir={remote_job_dir}",
            f"bash {remote_script}",
            "",
        ])

        with sftp.file(remote_script, "w") as handle:
            handle.write(runner_text)
        with sftp.file(remote_slurm, "w") as handle:
            handle.write(slurm_text)
        _run_remote(f"chmod 700 {shlex.quote(remote_script)} {shlex.quote(remote_slurm)}")

        # Submit the SLURM job
        submit_exit, submit_out, submit_err = _run_remote(
            f"cd {shlex.quote(remote_job_dir)} && sbatch --parsable {shlex.quote(remote_slurm)}"
        )
        if submit_exit != 0:
            details = submit_err or submit_out or f"exit status {submit_exit}"
            friendly = classify_slurm_resource_message(details)
            if friendly:
                details = f"{friendly} SLURM response: {details}"
            raise RuntimeError(f"Unable to submit ColabFold SLURM job for {genome}: {details}")

        run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()
        job_id = submit_out.split(";")[0].strip()
        if not job_id:
            raise RuntimeError(f"Unable to parse SLURM job id for ColabFold on {genome}")

        print(f"ColabFold remote: submitted SLURM job {job_id} on partition {config.slurm_partition}")
        _record_remote_job(
            run_id_raw,
            job_id=job_id,
            remote_job_dir=remote_job_dir,
        )

        remote_stdout = f"{remote_job_dir}/slurm-{job_id}.out"
        remote_stderr = f"{remote_job_dir}/slurm-{job_id}.err"

        # Poll for completion
        finished = False
        waited_seconds = 0
        last_state = "PENDING"
        completion_seen_at = None
        last_wait_notice = None

        while not finished and waited_seconds <= config.remote_wait_seconds:
            # Check if DONE marker exists (colabfold_batch finished successfully)
            done_exit, _, _ = _run_remote(f"test -f {shlex.quote(remote_done_marker)}")
            if done_exit == 0:
                finished = True
                continue

            # Check SLURM job state
            _, state_out, state_err = _run_remote(
                f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n | head -n 1"
            )
            state_line = state_out.splitlines()[0].strip() if state_out.strip() else ""
            state_parts = state_line.split("|") if state_line else []

            if len(state_parts) >= 3:
                _, remote_state, remote_exit_code = state_parts[:3]
                last_state = remote_state or last_state
                normalized = remote_state.upper()

                # Check for queue wait reasons
                _, queue_out, _ = _run_remote(
                    f"squeue -j {shlex.quote(job_id)} -h -o '%T|%R' 2>/dev/null | head -n 1"
                )
                queue_line = queue_out.splitlines()[0].strip() if queue_out.strip() else ""
                queue_parts = queue_line.split("|", 1) if queue_line else []
                queue_reason = queue_parts[1].strip() if len(queue_parts) == 2 else ""
                wait_notice = classify_slurm_resource_message(queue_reason, running=True)
                if wait_notice and wait_notice != last_wait_notice:
                    # Rewrite for ColabFold context
                    wait_notice = wait_notice.replace("InterProScan", "ColabFold")
                    _record_remote_info(
                        run_id_raw,
                        stage_number=16,
                        message=wait_notice,
                        payload={"remote_state": remote_state, "remote_reason": queue_reason},
                    )
                    last_wait_notice = wait_notice

                if normalized.startswith(REMOTE_FAILURE_PREFIXES):
                    _, slurm_out_text, _ = _run_remote(
                        f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true"
                    )
                    _, slurm_err_text, _ = _run_remote(
                        f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true"
                    )
                    details = slurm_err_text or slurm_out_text or state_err or "no remote output"
                    friendly = classify_slurm_resource_message(details)
                    if friendly:
                        details = f"{friendly} SLURM details: {details}"
                    raise RuntimeError(
                        f"Remote ColabFold failed for {genome} "
                        f"({remote_state} / {remote_exit_code}): {details}"
                    )

                if normalized.startswith("COMPLETED"):
                    if completion_seen_at is None:
                        completion_seen_at = waited_seconds
                    elif (waited_seconds - completion_seen_at) >= config.remote_completion_grace_seconds:
                        _, slurm_out_text, _ = _run_remote(
                            f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true"
                        )
                        _, slurm_err_text, _ = _run_remote(
                            f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true"
                        )
                        details = slurm_err_text or slurm_out_text or "no remote output"
                        raise RuntimeError(
                            f"Remote ColabFold finished for {genome} but DONE marker not found "
                            f"after {config.remote_completion_grace_seconds}s grace period. "
                            f"Details: {details}"
                        )

            # Print progress from the SLURM log if available
            _, progress_out, _ = _run_remote(
                f"grep -c 'rank_001' {shlex.quote(remote_output_dir)}/*.pdb 2>/dev/null | wc -l || echo 0"
            )
            print(
                f"ColabFold remote: waiting (state={last_state}, "
                f"{waited_seconds}s elapsed, polling every {config.remote_poll_seconds}s)"
            )

            time.sleep(config.remote_poll_seconds)
            waited_seconds += config.remote_poll_seconds

        if not finished:
            # Cancel the orphan GPU job before raising
            try:
                _run_remote(f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"ColabFold remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
            raise TimeoutError(
                f"ColabFold output not retrieved for {genome} after "
                f"{waited_seconds}s (last remote state: {last_state})"
            )

        # Download results — SCP the entire output directory
        local_results_dir = os.path.join(local_tmpdir, "output")
        os.makedirs(local_results_dir, exist_ok=True)
        scp_client.get(remote_output_dir, local_results_dir, recursive=True)

        # The SCP recursive get places files in local_results_dir/output/
        actual_results = os.path.join(local_results_dir, "output")
        if not os.path.isdir(actual_results):
            actual_results = local_results_dir

        # Distribute PDBs to alphafold/<locus_tag>/<locus_tag>_af.pdb
        alphafold_dir = os.path.join(folder_path, "alphafold")
        predicted = 0
        failed = 0
        for locus_tag, _ in candidates:
            pdb_src = _find_best_pdb(actual_results, locus_tag)
            if pdb_src is None:
                print(f"  ColabFold: no PDB produced for {locus_tag}")
                failed += 1
                continue
            locus_dir = os.path.join(alphafold_dir, locus_tag)
            os.makedirs(locus_dir, exist_ok=True)
            pdb_dst = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
            shutil.copy2(pdb_src, pdb_dst)
            print(f"  ColabFold: saved structure for {locus_tag}")
            predicted += 1

        print(f"ColabFold remote done: {predicted} predicted, {failed} failed")

        if predicted == 0 and len(candidates) > 0:
            raise RuntimeError(
                f"ColabFold remote produced no structures for {genome} "
                f"({len(candidates)} candidates)"
            )

        return predicted

    finally:
        # Cancel orphan SLURM job if we exit without finishing
        if not finished and job_id and ssh is not None:
            try:
                ssh.exec_command(f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"ColabFold remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
        if scp_client is not None:
            try:
                scp_client.close()
            except Exception:
                pass
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass
        # Clean up local temp dir
        try:
            shutil.rmtree(local_tmpdir, ignore_errors=True)
        except Exception:
            pass

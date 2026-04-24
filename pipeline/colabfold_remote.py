"""
Run ColabFold on a remote SLURM GPU node via SSH.

Analogous to interproscan_remote.py: SSH → SCP input → sbatch → poll → SCP results.
Activated when TPW_COLABFOLD_USE_REMOTE=1 is set; otherwise stage 16 runs locally.

The remote path:
  1. Identifies proteins without an existing structure.
  2. Runs one SLURM GPU job per protein when the sequence length is within the
     configured safe VRAM envelope.
  3. Falls back to remote ColabFold-on-CPU on the cluster for proteins above
     the GPU length limit or when an individual GPU job fails.
  4. Places results into alphafold/<locus_tag>/<locus_tag>_af.pdb.
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
    max_sequence_length: int
    gpu_slurm_partition: str
    gpu_slurm_time: str
    gpu_slurm_mem: str
    gpu_slurm_gres: str
    gpu_slurm_cpus_per_task: int
    gpu_slurm_exclude: str
    strict_gpu: bool
    cpu_slurm_partition: str
    cpu_slurm_time: str
    cpu_slurm_mem: str
    cpu_slurm_cpus_per_task: int


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
        max_sequence_length=_env_int("TPW_COLABFOLD_MAX_SEQ_LENGTH", default=800),
        gpu_slurm_partition=os.getenv("TPW_COLABFOLD_PARTITION", "gpu"),
        gpu_slurm_time=os.getenv("TPW_COLABFOLD_TIME", "12:00:00"),
        gpu_slurm_mem=os.getenv("TPW_COLABFOLD_MEM", "16gb"),
        gpu_slurm_gres=os.getenv("TPW_COLABFOLD_GRES", "gpu:1"),
        gpu_slurm_cpus_per_task=_env_int("TPW_COLABFOLD_CPUS", default=4),
        gpu_slurm_exclude=os.getenv("TPW_COLABFOLD_EXCLUDE", "").strip(),
        strict_gpu=_env_text("TPW_COLABFOLD_STRICT", default="").strip().lower()
            in ("1", "true", "yes"),
        cpu_slurm_partition=os.getenv("TPW_COLABFOLD_CPU_PARTITION", "cpu"),
        cpu_slurm_time=os.getenv("TPW_COLABFOLD_CPU_TIME", "24:00:00"),
        cpu_slurm_mem=os.getenv("TPW_COLABFOLD_CPU_MEM", "32gb"),
        cpu_slurm_cpus_per_task=_env_int("TPW_COLABFOLD_CPU_CPUS", default=8),
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


def _copy_predicted_pdb(results_dir, folder_path, locus_tag):
    pdb_src = _find_best_pdb(results_dir, locus_tag)
    if pdb_src is None:
        raise RuntimeError(f"No ColabFold rank_001 PDB produced for {locus_tag}")
    locus_dir = os.path.join(folder_path, "alphafold", locus_tag)
    os.makedirs(locus_dir, exist_ok=True)
    pdb_dst = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
    shutil.copy2(pdb_src, pdb_dst)
    return pdb_dst


def _run_remote_colabfold_candidate(
    *,
    ssh,
    scp_client,
    sftp,
    config,
    run_id_raw,
    folder_path,
    genome,
    locus_tag,
    sequence,
    mode,
    fallback_reason=None,
):
    import tempfile

    job_id = None
    finished = False

    def _run_remote(command):
        stdin, stdout, stderr = ssh.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return exit_code, out, err

    safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
    safe_locus = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in locus_tag)
    run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    remote_job_dir = (
        f"{config.ssh_rootfolder.rstrip('/')}/tpw_colabfold/"
        f"{safe_genome}_{safe_locus}_{mode}_{run_label}"
    )
    remote_input = f"{remote_job_dir}/input.fasta"
    remote_output_dir = f"{remote_job_dir}/output"
    remote_script = f"{remote_job_dir}/run_colabfold.sh"
    remote_slurm = f"{remote_job_dir}/colabfold.slurm"
    remote_done_marker = f"{remote_job_dir}/DONE"
    remote_stdout_pattern = f"{remote_job_dir}/slurm-%j.out"
    remote_stderr_pattern = f"{remote_job_dir}/slurm-%j.err"

    if mode == "gpu":
        slurm_partition = config.gpu_slurm_partition
        slurm_time = config.gpu_slurm_time
        slurm_mem = config.gpu_slurm_mem
        slurm_gres = config.gpu_slurm_gres
        slurm_cpus = config.gpu_slurm_cpus_per_task
        slurm_exclude = config.gpu_slurm_exclude
        job_prefix = "cfg"
        mode_label = "GPU"
    elif mode == "cpu":
        slurm_partition = config.cpu_slurm_partition
        slurm_time = config.cpu_slurm_time
        slurm_mem = config.cpu_slurm_mem
        slurm_gres = ""
        slurm_cpus = config.cpu_slurm_cpus_per_task
        slurm_exclude = ""
        job_prefix = "cfc"
        mode_label = "CPU"
    else:
        raise ValueError(f"Unknown ColabFold execution mode: {mode}")

    try:
        with tempfile.TemporaryDirectory(prefix=f"colabfold_remote_{locus_tag}_") as local_tmpdir:
            local_input_fasta = os.path.join(local_tmpdir, "input.fasta")
            with open(local_input_fasta, "w", encoding="utf-8") as handle:
                handle.write(f">{locus_tag}\n{sequence}\n")

            mkdir_exit, _, mkdir_err = _run_remote(f"mkdir -p {shlex.quote(remote_job_dir)}")
            if mkdir_exit != 0:
                raise RuntimeError(
                    f"Unable to create remote ColabFold directory for {locus_tag}: "
                    f"{mkdir_err or f'exit {mkdir_exit}'}"
                )

            scp_client.put(local_input_fasta, remote_input)

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

            slurm_text = "\n".join([
                "#!/bin/bash",
                f"#SBATCH --job-name={job_prefix}_{safe_locus[:20]}",
                f"#SBATCH -p {slurm_partition}",
                *((f"#SBATCH --gres={slurm_gres}",) if slurm_gres else ()),
                *((f"#SBATCH --exclude={slurm_exclude}",) if slurm_exclude else ()),
                f"#SBATCH --cpus-per-task={slurm_cpus}",
                f"#SBATCH --time={slurm_time}",
                f"#SBATCH --mem={slurm_mem}",
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

            submit_exit, submit_out, submit_err = _run_remote(
                f"cd {shlex.quote(remote_job_dir)} && sbatch --parsable {shlex.quote(remote_slurm)}"
            )
            if submit_exit != 0:
                details = submit_err or submit_out or f"exit status {submit_exit}"
                friendly = classify_slurm_resource_message(details)
                if friendly:
                    details = f"{friendly} SLURM response: {details}"
                raise RuntimeError(
                    f"Unable to submit ColabFold SLURM job for {locus_tag}: {details}"
                )

            job_id = submit_out.split(";")[0].strip()
            if not job_id:
                raise RuntimeError(f"Unable to parse SLURM job id for ColabFold on {locus_tag}")

            print(
                f"ColabFold remote: submitted {mode_label} SLURM job {job_id} for "
                f"{locus_tag} ({len(sequence)} aa) on partition {slurm_partition}"
            )
            _record_remote_job(
                run_id_raw,
                job_id=job_id,
                remote_job_dir=remote_job_dir,
            )
            _record_remote_info(
                run_id_raw,
                stage_number=16,
                message=f"Submitted remote ColabFold {mode_label} job {job_id} for {locus_tag}",
                payload={
                    "job_id": job_id,
                    "remote_job_dir": remote_job_dir,
                    "locus_tag": locus_tag,
                    "mode": mode,
                    "fallback_reason": fallback_reason,
                },
            )

            remote_stdout = f"{remote_job_dir}/slurm-{job_id}.out"
            remote_stderr = f"{remote_job_dir}/slurm-{job_id}.err"
            waited_seconds = 0
            last_state = "PENDING"
            completion_seen_at = None
            last_wait_notice = None

            while not finished and waited_seconds <= config.remote_wait_seconds:
                done_exit, _, _ = _run_remote(f"test -f {shlex.quote(remote_done_marker)}")
                if done_exit == 0:
                    finished = True
                    continue

                _, state_out, state_err = _run_remote(
                    f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n | head -n 1"
                )
                state_line = state_out.splitlines()[0].strip() if state_out.strip() else ""
                state_parts = state_line.split("|") if state_line else []

                if len(state_parts) >= 3:
                    _, remote_state, remote_exit_code = state_parts[:3]
                    last_state = remote_state or last_state
                    normalized = remote_state.upper()
                    _, queue_out, _ = _run_remote(
                        f"squeue -j {shlex.quote(job_id)} -h -o '%T|%R' 2>/dev/null | head -n 1"
                    )
                    queue_line = queue_out.splitlines()[0].strip() if queue_out.strip() else ""
                    queue_parts = queue_line.split("|", 1) if queue_line else []
                    queue_reason = queue_parts[1].strip() if len(queue_parts) == 2 else ""
                    wait_notice = classify_slurm_resource_message(queue_reason, running=True)
                    if wait_notice and wait_notice != last_wait_notice:
                        wait_notice = wait_notice.replace("InterProScan", "ColabFold")
                        _record_remote_info(
                            run_id_raw,
                            stage_number=16,
                            message=f"{wait_notice} ({locus_tag})",
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
                            f"Remote ColabFold failed for {locus_tag} "
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
                                f"Remote ColabFold finished for {locus_tag} but DONE marker not found "
                                f"after {config.remote_completion_grace_seconds}s grace period. "
                                f"Details: {details}"
                            )

                print(
                    f"ColabFold remote ({mode_label}): waiting for {locus_tag} "
                    f"(state={last_state}, {waited_seconds}s elapsed)"
                )
                time.sleep(config.remote_poll_seconds)
                waited_seconds += config.remote_poll_seconds

            if not finished:
                raise TimeoutError(
                    f"ColabFold output not retrieved for {locus_tag} after "
                    f"{waited_seconds}s (last remote state: {last_state})"
                )

            local_results_dir = os.path.join(local_tmpdir, "output")
            os.makedirs(local_results_dir, exist_ok=True)
            scp_client.get(remote_output_dir, local_results_dir, recursive=True)
            actual_results = os.path.join(local_results_dir, "output")
            if not os.path.isdir(actual_results):
                actual_results = local_results_dir

            _copy_predicted_pdb(actual_results, folder_path, locus_tag)
            print(f"  ColabFold remote ({mode_label}): saved structure for {locus_tag}")
    finally:
        if not finished and job_id:
            try:
                _run_remote(f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"ColabFold remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_remote_colabfold(cfg_dict, folder_path, genome):
    """
    Run ColabFold on a remote SLURM GPU node.

    1. Identify proteins without structures yet.
    2. Run one GPU job per protein for candidates within the VRAM-safe limit.
    3. Fall back to remote CPU ColabFold on the cluster for long proteins or per-protein GPU failures.
    4. Place results in alphafold/<locus_tag>/<locus_tag>_af.pdb.

    Returns the number of predicted structures.
    """
    config = _build_colabfold_config(cfg_dict)

    candidates = _find_candidates(folder_path, genome)
    if not candidates:
        print("ColabFold remote: no candidates to predict.")
        return 0

    print(
        f"ColabFold remote: {len(candidates)} proteins to predict "
        f"(GPU <= {config.max_sequence_length} aa, remote CPU fallback otherwise)."
    )

    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    ssh = None
    scp_client = None
    sftp = None
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
        scp_client = SCPClient(ssh.get_transport())
        sftp = ssh.open_sftp()
        run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()
        predicted = 0

        for locus_tag, sequence in candidates:
            if config.max_sequence_length > 0 and len(sequence) > config.max_sequence_length:
                _record_remote_info(
                    run_id_raw,
                    stage_number=16,
                    message=(
                        f"Using remote CPU ColabFold fallback for {locus_tag} "
                        f"({len(sequence)} aa exceeds GPU limit {config.max_sequence_length} aa)."
                    ),
                    payload={"locus_tag": locus_tag, "length": len(sequence)},
                )
                _run_remote_colabfold_candidate(
                    ssh=ssh,
                    scp_client=scp_client,
                    sftp=sftp,
                    config=config,
                    run_id_raw=run_id_raw,
                    folder_path=folder_path,
                    genome=genome,
                    locus_tag=locus_tag,
                    sequence=sequence,
                    mode="cpu",
                    fallback_reason=(
                        f"length {len(sequence)} aa exceeds GPU limit "
                        f"{config.max_sequence_length} aa"
                    ),
                )
                predicted += 1
                continue

            try:
                _run_remote_colabfold_candidate(
                    ssh=ssh,
                    scp_client=scp_client,
                    sftp=sftp,
                    config=config,
                    run_id_raw=run_id_raw,
                    folder_path=folder_path,
                    genome=genome,
                    locus_tag=locus_tag,
                    sequence=sequence,
                    mode="gpu",
                )
                predicted += 1
            except Exception as exc:
                if config.strict_gpu:
                    _record_remote_info(
                        run_id_raw,
                        stage_number=16,
                        message=(
                            f"Remote ColabFold GPU failed for {locus_tag}; "
                            f"strict mode on, aborting. Details: {exc}"
                        )[:1000],
                        payload={"locus_tag": locus_tag},
                    )
                    raise
                _record_remote_info(
                    run_id_raw,
                    stage_number=16,
                    message=(
                        f"Remote ColabFold failed for {locus_tag}; "
                        f"falling back to remote CPU. Details: {exc}"
                    )[:1000],
                    payload={"locus_tag": locus_tag},
                )
                _run_remote_colabfold_candidate(
                    ssh=ssh,
                    scp_client=scp_client,
                    sftp=sftp,
                    config=config,
                    run_id_raw=run_id_raw,
                    folder_path=folder_path,
                    genome=genome,
                    locus_tag=locus_tag,
                    sequence=sequence,
                    mode="cpu",
                    fallback_reason=f"remote GPU failure: {exc}",
                )
                predicted += 1

        print(f"ColabFold stage 16 done: {predicted} predicted")
        return predicted

    finally:
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

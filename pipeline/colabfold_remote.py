"""
Run ColabFold on a remote SLURM GPU node via SSH.

Analogous to interproscan_remote.py: SSH → SCP input → sbatch → poll → SCP results.
Activated when TPW_COLABFOLD_USE_REMOTE=1 is set; otherwise stage 16 runs locally.

The remote path:
  1. Identifies proteins without an existing structure.
  2. Runs one SLURM GPU job per protein when the sequence length is within the
     configured safe VRAM envelope -- or, with TPW_COLABFOLD_BATCH_SIZE > 1,
     first one job per length-sorted batch, then per protein for leftovers.
  3. Falls back to remote ColabFold-on-CPU on the cluster for proteins above
     the GPU length limit or when an individual GPU job fails.
  4. Places results into alphafold/<locus_tag>/<locus_tag>_af.pdb.
"""

import gzip
import os
import shlex
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

import paramiko
from slurm_remote_command import (
    REMOTE_FAILURE_PREFIXES,
    _assert_ssh_reachable,
    _close_remote_session,
    _config_text,
    _exec_remote,
    _env_int,
    _env_text,
    _open_remote_session,
    _resolve_ssh_options,
)
from tpweb.services.slurm_messages import classify_slurm_resource_message


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
    gpu_pending_wait_seconds: int
    cpu_pending_wait_seconds: int
    remote_completion_grace_seconds: int
    ssh_outage_wait_seconds: int
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
    max_parallel: int
    batch_size: int
    cpu_catchup_max_parallel: int
    gpu_retry_attempts: int
    cpu_slurm_partition: str
    cpu_slurm_time: str
    cpu_slurm_mem: str
    cpu_slurm_cpus_per_task: int
    cpu_slurm_exclude: str
    cpu_retry_attempts: int


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
        gpu_pending_wait_seconds=_env_int(
            "TPW_COLABFOLD_GPU_PENDING_WAIT_SEC",
            default=0,
        ),
        cpu_pending_wait_seconds=_env_int(
            "TPW_COLABFOLD_CPU_PENDING_WAIT_SEC",
            default=0,
        ),
        remote_completion_grace_seconds=_env_int(
            "TPW_COLABFOLD_REMOTE_COMPLETION_GRACE_SEC",
            default=120,
        ),
        # How long to keep retrying while the cluster's SSH is unreachable
        # before giving up on a job. A short outage (observed: ~minutes at
        # night) used to fail every in-flight and queued batch at once.
        ssh_outage_wait_seconds=_env_int("TPW_COLABFOLD_SSH_OUTAGE_WAIT_SEC", default=21600),
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
        max_parallel=_env_int("TPW_COLABFOLD_MAX_PARALLEL", default=8),
        # Proteins per GPU SLURM job in the batched first pass (see
        # run_remote_colabfold). 1 = no batch pass, one job per protein.
        batch_size=max(1, _env_int("TPW_COLABFOLD_BATCH_SIZE", default=1)),
        # Deliberately separate from max_parallel: the GPU-fast pass and the
        # CPU-catch-up pass never run at the same time (see
        # run_remote_colabfold), but a CPU job is much heavier per-worker
        # (8 CPUs/32GB each, cpu_slurm_cpus_per_task/cpu_slurm_mem below) --
        # letting operators cap catch-up concurrency independently of the
        # GPU pass's concurrency.
        cpu_catchup_max_parallel=_env_int(
            "TPW_COLABFOLD_CPU_MAX_PARALLEL",
            default=_env_int("TPW_COLABFOLD_MAX_PARALLEL", default=8),
        ),
        gpu_retry_attempts=_env_int("TPW_COLABFOLD_GPU_RETRIES", default=1),
        cpu_slurm_partition=os.getenv("TPW_COLABFOLD_CPU_PARTITION", "cpu"),
        cpu_slurm_time=os.getenv("TPW_COLABFOLD_CPU_TIME", "24:00:00"),
        cpu_slurm_mem=os.getenv("TPW_COLABFOLD_CPU_MEM", "32gb"),
        cpu_slurm_cpus_per_task=_env_int("TPW_COLABFOLD_CPU_CPUS", default=8),
        cpu_slurm_exclude=os.getenv(
            "TPW_COLABFOLD_CPU_EXCLUDE",
            os.getenv("TPW_COLABFOLD_EXCLUDE", ""),
        ).strip(),
        cpu_retry_attempts=_env_int("TPW_COLABFOLD_CPU_RETRIES", default=2),
    )


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


class ColabFoldJobError(RuntimeError):
    """A ColabFold job genuinely failed or timed out on the cluster side --
    as opposed to a dropped SSH connection, which is retried. Subclasses
    RuntimeError (not the builtin TimeoutError) on purpose: in Python 3.10
    socket.timeout *is* TimeoutError, so a job timeout raised as
    TimeoutError would be indistinguishable from a network timeout."""


def _is_connection_error(exc):
    return isinstance(exc, OSError | EOFError | paramiko.SSHException) and not isinstance(
        exc, ColabFoldJobError
    )


def _open_session_waiting(config, *, retry_seconds=60):
    """_open_remote_session, but rides out a cluster SSH outage of up to
    config.ssh_outage_wait_seconds instead of failing immediately."""
    waited = 0
    while True:
        try:
            return _open_remote_session(config)
        except Exception as exc:
            if not _is_connection_error(exc) or waited >= config.ssh_outage_wait_seconds:
                raise
            print(
                f"ColabFold remote: cluster SSH unreachable ({exc}); retrying in {retry_seconds}s"
            )
            time.sleep(retry_seconds)
            waited += retry_seconds


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

    return [(tag, seq) for tag, seq in sequences.items() if tag not in already_have]


def _find_best_pdb(directory, locus_tag):
    """Find the rank_001 PDB produced by colabfold_batch for a locus_tag."""
    try:
        candidates = [
            f
            for f in os.listdir(directory)
            if f.startswith(locus_tag + "_") and "rank_001" in f and f.endswith(".pdb")
        ]
    except FileNotFoundError:
        return None
    if not candidates:
        return None
    candidates.sort()
    return os.path.join(directory, candidates[0])


def _find_batch_pdb(directory, locus_tag):
    """Exact-name rank_001 lookup for a batch's shared output dir.

    _find_best_pdb's plain ``locus_tag + "_"`` prefix is fine with one
    protein per dir, but in a batch ``X_1`` would also match ``X_1_2``'s
    files -- so require ColabFold's own ``<jobname>_(un)relaxed_rank_001``
    naming instead."""
    prefixes = (f"{locus_tag}_unrelaxed_rank_001", f"{locus_tag}_relaxed_rank_001")
    try:
        names = sorted(
            f for f in os.listdir(directory) if f.startswith(prefixes) and f.endswith(".pdb")
        )
    except FileNotFoundError:
        return None
    return os.path.join(directory, names[0]) if names else None


def _copy_predicted_pdb(results_dir, folder_path, locus_tag, *, exact=False):
    pdb_src = (_find_batch_pdb if exact else _find_best_pdb)(results_dir, locus_tag)
    if pdb_src is None:
        raise RuntimeError(f"No ColabFold rank_001 PDB produced for {locus_tag}")
    locus_dir = os.path.join(folder_path, "alphafold", locus_tag)
    os.makedirs(locus_dir, exist_ok=True)
    pdb_dst = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
    shutil.copy2(pdb_src, pdb_dst)
    return pdb_dst


def _run_remote_colabfold_job(
    *,
    ssh,
    scp_client,
    sftp,
    config,
    run_id_raw,
    folder_path,
    genome,
    entries,
    mode,
    fallback_reason=None,
    batch=False,
):
    """Run one ColabFold SLURM job over ``entries`` ((locus_tag, sequence)
    pairs) and save each rank_001 PDB into the workspace.

    Single-protein (``batch=False``): exactly the original per-protein job --
    a missing PDB raises. Batch: colabfold_batch failing partway still
    touches DONE (``|| echo``), so whatever it finished is kept; the caller
    gets the saved locus tags back and retries the rest one by one. Returns
    the list of locus tags whose structure was saved."""
    import tempfile

    locus_tag = entries[0][0]
    if batch:
        lengths = [len(seq) for _, seq in entries]
        label = f"batch of {len(entries)} ({entries[0][0]}..{entries[-1][0]})"
        size_text = f"{min(lengths)}-{max(lengths)} aa"
        job_tag = f"b{len(entries)}_{locus_tag}"
    else:
        label = locus_tag
        size_text = f"{len(entries[0][1])} aa"
        job_tag = locus_tag

    job_id = None
    finished = False
    # Replaced in place by _reconnect() if the connection drops mid-job, so
    # an SSH outage while waiting on SLURM doesn't abandon the running job.
    session = {"ssh": ssh, "scp": scp_client, "sftp": sftp}
    reopened = []

    def _run_remote(command):
        stdin, stdout, stderr = session["ssh"].exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return exit_code, out, err

    def _reconnect(exc):
        print(f"ColabFold remote: connection lost while handling {label} ({exc}); reconnecting")
        new_session = _open_session_waiting(config)
        reopened.append(new_session)
        session["ssh"], session["scp"], session["sftp"] = new_session

    safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
    safe_locus = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in job_tag)
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
        slurm_exclude = config.cpu_slurm_exclude
        job_prefix = "cfc"
        mode_label = "CPU"
    else:
        raise ValueError(f"Unknown ColabFold execution mode: {mode}")

    try:
        with tempfile.TemporaryDirectory(prefix=f"colabfold_remote_{locus_tag}_") as local_tmpdir:
            local_input_fasta = os.path.join(local_tmpdir, "input.fasta")
            with open(local_input_fasta, "w", encoding="utf-8") as handle:
                for entry_tag, entry_seq in entries:
                    handle.write(f">{entry_tag}\n{entry_seq}\n")

            mkdir_exit, _, mkdir_err = _run_remote(f"mkdir -p {shlex.quote(remote_job_dir)}")
            if mkdir_exit != 0:
                raise RuntimeError(
                    f"Unable to create remote ColabFold directory for {label}: "
                    f"{mkdir_err or f'exit {mkdir_exit}'}"
                )

            scp_client.put(local_input_fasta, remote_input)

            cpu_only_exports = []
            if mode == "cpu":
                # Force ColabFold/JAX/TensorFlow onto CPU for fallback jobs.
                cpu_only_exports = [
                    "export CUDA_VISIBLE_DEVICES=''",
                    "export JAX_PLATFORMS=cpu",
                    "export JAX_PLATFORM_NAME=cpu",
                ]

            runner_text = "\n".join(
                [
                    "#!/bin/bash",
                    "set -eo pipefail",
                    f'eval "$({config.conda_prefix}/bin/conda shell.bash hook)"',
                    f"conda activate {shlex.quote(config.conda_env)}",
                    "set -u",
                    f"mkdir -p {shlex.quote(remote_output_dir)}",
                    *cpu_only_exports,
                    (
                        f"colabfold_batch"
                        f" {shlex.quote(remote_input)}"
                        f" {shlex.quote(remote_output_dir)}"
                        f" --num-recycle {config.num_recycles}"
                        f" --num-models {config.num_models}"
                        f" --model-type alphafold2_ptm"
                        + (
                            # Keep what finished if one query aborts the run;
                            # missing PDBs get retried one by one.
                            ' || echo "colabfold_batch exited with status $?" >&2' if batch else ""
                        )
                    ),
                    f"touch {shlex.quote(remote_done_marker)}",
                    "",
                ]
            )

            slurm_text = "\n".join(
                [
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
                ]
            )

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
                friendly = classify_slurm_resource_message(details, tool_label="ColabFold")
                if friendly:
                    details = f"{friendly} SLURM response: {details}"
                raise RuntimeError(f"Unable to submit ColabFold SLURM job for {label}: {details}")

            job_id = submit_out.split(";")[0].strip()
            if not job_id:
                raise RuntimeError(f"Unable to parse SLURM job id for ColabFold on {label}")

            print(
                f"ColabFold remote: submitted {mode_label} SLURM job {job_id} for "
                f"{label} ({size_text}) on partition {slurm_partition}"
            )
            _record_remote_job(
                run_id_raw,
                job_id=job_id,
                remote_job_dir=remote_job_dir,
            )
            _record_remote_info(
                run_id_raw,
                stage_number=16,
                message=f"Submitted remote ColabFold {mode_label} job {job_id} for {label}",
                payload={
                    "job_id": job_id,
                    "remote_job_dir": remote_job_dir,
                    "locus_tag": locus_tag,
                    "locus_tags": [tag for tag, _ in entries] if batch else [locus_tag],
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
            pending_wait_limit = (
                config.gpu_pending_wait_seconds
                if mode == "gpu"
                else config.cpu_pending_wait_seconds
            )

            while not finished and waited_seconds <= config.remote_wait_seconds:
                try:
                    done_exit, _, _ = _run_remote(f"test -f {shlex.quote(remote_done_marker)}")
                    if done_exit == 0:
                        finished = True
                        continue

                    _, state_out, state_err = _run_remote(
                        f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n"
                        " | head -n 1"
                    )
                    _, queue_out, _ = _run_remote(
                        f"squeue -j {shlex.quote(job_id)} -h -o '%T|%R' 2>/dev/null | head -n 1"
                    )
                except Exception as exc:
                    if not _is_connection_error(exc):
                        raise
                    _reconnect(exc)
                    continue
                state_line = state_out.splitlines()[0].strip() if state_out.strip() else ""
                state_parts = state_line.split("|") if state_line else []

                if len(state_parts) >= 3:
                    _, remote_state, remote_exit_code = state_parts[:3]
                    last_state = remote_state or last_state
                    normalized = remote_state.upper()
                    queue_line = queue_out.splitlines()[0].strip() if queue_out.strip() else ""
                    queue_parts = queue_line.split("|", 1) if queue_line else []
                    queue_reason = queue_parts[1].strip() if len(queue_parts) == 2 else ""
                    wait_notice = classify_slurm_resource_message(
                        queue_reason, running=True, tool_label="ColabFold"
                    )
                    if wait_notice and wait_notice != last_wait_notice:
                        _record_remote_info(
                            run_id_raw,
                            stage_number=16,
                            message=f"{wait_notice} ({label})",
                            payload={"remote_state": remote_state, "remote_reason": queue_reason},
                        )
                        last_wait_notice = wait_notice

                    if (
                        pending_wait_limit > 0
                        and normalized.startswith("PENDING")
                        and waited_seconds >= pending_wait_limit
                    ):
                        raise ColabFoldJobError(
                            f"ColabFold job for {label} stayed PENDING for "
                            f"{waited_seconds}s, exceeding {mode_label} pending wait limit "
                            f"{pending_wait_limit}s"
                        )

                    if normalized.startswith(REMOTE_FAILURE_PREFIXES):
                        _, slurm_out_text, _ = _run_remote(
                            f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true"
                        )
                        _, slurm_err_text, _ = _run_remote(
                            f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true"
                        )
                        details = (
                            slurm_err_text or slurm_out_text or state_err or "no remote output"
                        )
                        friendly = classify_slurm_resource_message(details, tool_label="ColabFold")
                        if friendly:
                            details = f"{friendly} SLURM details: {details}"
                        raise ColabFoldJobError(
                            f"Remote ColabFold failed for {label} "
                            f"({remote_state} / {remote_exit_code}): {details}"
                        )

                    if normalized.startswith("COMPLETED"):
                        if completion_seen_at is None:
                            completion_seen_at = waited_seconds
                        elif (
                            waited_seconds - completion_seen_at
                        ) >= config.remote_completion_grace_seconds:
                            _, slurm_out_text, _ = _run_remote(
                                f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true"
                            )
                            _, slurm_err_text, _ = _run_remote(
                                f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true"
                            )
                            details = slurm_err_text or slurm_out_text or "no remote output"
                            raise ColabFoldJobError(
                                f"Remote ColabFold finished for {label} but DONE marker not found "
                                f"after {config.remote_completion_grace_seconds}s grace period. "
                                f"Details: {details}"
                            )

                print(
                    f"ColabFold remote ({mode_label}): waiting for {label} "
                    f"(state={last_state}, {waited_seconds}s elapsed)"
                )
                time.sleep(config.remote_poll_seconds)
                waited_seconds += config.remote_poll_seconds

            if not finished:
                raise ColabFoldJobError(
                    f"ColabFold output not retrieved for {label} after "
                    f"{waited_seconds}s (last remote state: {last_state})"
                )

            local_results_dir = os.path.join(local_tmpdir, "output")
            os.makedirs(local_results_dir, exist_ok=True)
            for attempt in range(3):
                try:
                    _fetch_job_outputs(session, remote_output_dir, local_results_dir, batch=batch)
                    break
                except Exception as exc:
                    if not _is_connection_error(exc) or attempt == 2:
                        raise
                    _reconnect(exc)

            if not batch:
                actual_results = os.path.join(local_results_dir, "output")
                if not os.path.isdir(actual_results):
                    actual_results = local_results_dir

                _copy_predicted_pdb(actual_results, folder_path, locus_tag)
                print(f"  ColabFold remote ({mode_label}): saved structure for {locus_tag}")
                return [locus_tag]

            saved = []
            for entry_tag, _ in entries:
                try:
                    _copy_predicted_pdb(local_results_dir, folder_path, entry_tag, exact=True)
                except RuntimeError:
                    continue
                saved.append(entry_tag)
            print(
                f"  ColabFold remote ({mode_label}): saved {len(saved)}/{len(entries)} "
                f"structures from {label}"
            )
            return saved
    finally:
        if not finished and job_id:
            try:
                _run_remote(f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"ColabFold remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
        for extra in reopened:
            _close_remote_session(*extra)


def _fetch_job_outputs(session, remote_output_dir, local_results_dir, *, batch):
    """Single job: the whole output dir, as before. Batch: only the
    rank_001 PDBs -- MSAs, PAE JSONs and plots for dozens of proteins are
    mostly unused weight."""
    if not batch:
        session["scp"].get(remote_output_dir, local_results_dir, recursive=True)
        return
    try:
        remote_names = session["sftp"].listdir(remote_output_dir)
    except FileNotFoundError:
        remote_names = []
    for name in remote_names:
        if "rank_001" in name and name.endswith(".pdb"):
            session["sftp"].get(
                f"{remote_output_dir}/{name}", os.path.join(local_results_dir, name)
            )


def _run_remote_colabfold_candidate(*, locus_tag, sequence, **kwargs):
    """One protein, one SLURM job -- raises if no PDB comes back."""
    return _run_remote_colabfold_job(entries=[(locus_tag, sequence)], batch=False, **kwargs)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_remote_colabfold(cfg_dict, folder_path, genome):
    """
    Run ColabFold on a remote SLURM GPU node, in two passes.

    0. Batched GPU pass (only when TPW_COLABFOLD_BATCH_SIZE > 1): GPU-eligible
       proteins sorted by length and chunked, one SLURM job per chunk. With
       one job per protein, most of each protein's wall-clock went to SLURM
       queueing, conda/ColabFold startup, model recompilation and the poll
       interval rather than the ~20-50s of actual GPU work; a batch pays
       those once and colabfold_batch reuses the compiled model across
       similar lengths. Anything a batch didn't produce (whole job failed,
       one query aborted the run) just falls through to step 1 below, so
       per-protein failure isolation is unchanged.
    1. GPU-fast pass: one SLURM GPU job per protein within the VRAM-safe
       length limit. A protein that's too long for GPU, or whose GPU
       attempt(s) fail, is *deferred* rather than retried on CPU inline --
       remote ColabFold-on-CPU can take many hours for a single protein,
       and retrying inline used to tie up one of this pass's worker threads
       for that whole time, starving every other protein still waiting on a
       GPU slot of concurrency (a genome with one unusually long/hard
       protein could see the other ~5000 crawl because only 2 of 8 workers
       were still free). Nothing in this pass waits on CPU jobs at all.
    2. CPU catch-up pass: runs only after the GPU pass fully finishes, over
       exactly the deferred proteins, with its own (optionally smaller)
       concurrency. Slow by nature, but isolated -- it no longer blocks the
       fast pass's throughput for the rest of the genome.
    3. Place results in alphafold/<locus_tag>/<locus_tag>_af.pdb.

    Returns the number of predicted structures.
    """
    config = _build_colabfold_config(cfg_dict)

    candidates = _find_candidates(folder_path, genome)
    if not candidates:
        print("ColabFold remote: no candidates to predict.")
        return 0

    print(
        f"ColabFold remote: {len(candidates)} proteins to predict "
        f"(GPU <= {config.max_sequence_length} aa, remote CPU catch-up pass otherwise)."
    )

    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()

    candidates = _recover_remote_outputs(config, folder_path, genome, candidates)
    if not candidates:
        print("ColabFold stage 16 done: every missing structure was recovered from the cluster")
        return 0

    predicted = 0
    if config.batch_size > 1:
        batched, candidates = _run_batched_gpu_pass(
            config, candidates, folder_path, genome, run_id_raw
        )
        predicted += batched
        if not candidates:
            print(f"ColabFold stage 16 done: {predicted} predicted")
            return predicted

    gpu_workers = max(1, min(config.max_parallel, len(candidates)))
    print(f"ColabFold remote: GPU-fast pass parallelism={gpu_workers}")

    deferred = []  # (locus_tag, sequence, fallback_reason)
    hard_failures = []  # (locus_tag, error) -- only possible in strict mode

    def run_gpu_phase(locus_tag, sequence):
        return _process_candidate_gpu_phase(
            config, locus_tag, sequence, folder_path, genome, run_id_raw
        )

    for locus_tag, result in _run_phase(run_gpu_phase, candidates, gpu_workers):
        if result is None:
            predicted += 1
        elif result[0] == "error":
            hard_failures.append((locus_tag, result[1]))
        else:
            _, sequence, reason = result
            deferred.append((locus_tag, sequence, reason))

    if deferred:
        print(
            f"ColabFold remote: GPU-fast pass done -- {predicted} predicted, "
            f"{len(deferred)} deferred to the CPU catch-up pass."
        )
        _record_remote_info(
            run_id_raw,
            stage_number=16,
            message=(
                f"GPU-fast pass done: {predicted} predicted, {len(deferred)} "
                "proteins deferred to the CPU catch-up pass."
            ),
            payload={"predicted": predicted, "deferred": len(deferred)},
        )

        cpu_workers = max(1, min(config.cpu_catchup_max_parallel, len(deferred)))
        print(f"ColabFold remote: CPU catch-up pass parallelism={cpu_workers}")

        def run_cpu_phase(locus_tag, payload):
            sequence, fallback_reason = payload
            return _process_candidate_cpu_catchup(
                config, locus_tag, sequence, folder_path, genome, run_id_raw, fallback_reason
            )

        catchup_items = [
            (locus_tag, (sequence, reason)) for locus_tag, sequence, reason in deferred
        ]
        for locus_tag, error in _run_phase(run_cpu_phase, catchup_items, cpu_workers):
            if error is None:
                predicted += 1
            else:
                hard_failures.append((locus_tag, error))

    if hard_failures:
        failed_tags = ", ".join(tag for tag, _ in hard_failures[:10])
        raise RuntimeError(
            f"ColabFold stage 16 incomplete for {len(hard_failures)} proteins. "
            f"Missing structures include: {failed_tags}"
        )
    print(f"ColabFold stage 16 done: {predicted} predicted")
    return predicted


def _recover_remote_outputs(config, folder_path, genome, candidates):
    """Pull rank_001 PDBs a previous, interrupted run left on the cluster.

    A batch whose orchestrator lost the connection (or was killed/restarted)
    keeps running on SLURM and writes its PDBs into its job dir, but nobody
    copies them back -- the next run would just predict those proteins again.
    Returns the candidates still missing afterwards."""
    wanted = {tag for tag, _ in candidates}
    safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
    root = f"{config.ssh_rootfolder.rstrip('/')}/tpw_colabfold"
    pattern = f"{root}/{safe_genome}_*/output/*_rank_001_*.pdb"

    ssh, scp_client, sftp = _open_session_waiting(config)
    recovered = 0
    try:
        _, out, _ = _exec_remote(ssh, f"ls -1 {pattern} 2>/dev/null || true")
        for remote_path in out.splitlines():
            name = os.path.basename(remote_path.strip())
            for marker in ("_unrelaxed_rank_001", "_relaxed_rank_001"):
                if marker in name:
                    tag = name.split(marker, 1)[0]
                    break
            else:
                continue
            if tag not in wanted or os.path.exists(_candidate_pdb_path(folder_path, tag)):
                continue
            locus_dir = os.path.join(folder_path, "alphafold", tag)
            os.makedirs(locus_dir, exist_ok=True)
            sftp.get(remote_path.strip(), _candidate_pdb_path(folder_path, tag))
            recovered += 1
    finally:
        _close_remote_session(ssh, scp_client, sftp)

    if recovered:
        print(f"ColabFold remote: recovered {recovered} structures left on the cluster")
    return [
        (tag, seq)
        for tag, seq in candidates
        if not os.path.exists(_candidate_pdb_path(folder_path, tag))
    ]


def _make_length_batches(entries, batch_size):
    """Chunk (locus_tag, sequence) pairs into batches of similar length, so
    each colabfold_batch run recompiles the model as little as possible."""
    ordered = sorted(entries, key=lambda entry: (len(entry[1]), entry[0]))
    return [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]


def _run_batched_gpu_pass(config, candidates, folder_path, genome, run_id_raw):
    """Step 0 of run_remote_colabfold. Returns (predicted_count, leftovers):
    every candidate without a saved PDB afterwards -- including the ones too
    long for GPU, which the per-protein pass defers to CPU as before."""
    eligible = [
        (tag, seq)
        for tag, seq in candidates
        if config.max_sequence_length <= 0 or len(seq) <= config.max_sequence_length
    ]
    batches = _make_length_batches(eligible, config.batch_size)
    if not batches:
        return 0, candidates

    workers = max(1, min(config.max_parallel, len(batches)))
    print(
        f"ColabFold remote: batched GPU pass -- {len(eligible)} proteins in "
        f"{len(batches)} jobs of up to {config.batch_size}, parallelism={workers}"
    )

    def run_batch(_batch_key, entries):
        try:
            return _run_batch_attempt(config, run_id_raw, folder_path, genome, entries)
        except Exception as exc:
            # Whole-batch failure (bad node, timeout, SLURM error): its
            # proteins just go through the per-protein pass instead.
            message = (
                f"Batched ColabFold job for {len(entries)} proteins "
                f"({entries[0][0]}..{entries[-1][0]}) failed; retrying them "
                f"one by one. Details: {exc}"
            )[:1000]
            print(f"ColabFold remote: {message}")
            _record_remote_info(
                run_id_raw,
                stage_number=16,
                message=message,
                payload={"locus_tags": [tag for tag, _ in entries]},
            )
            return []

    items = [(entries[0][0], entries) for entries in batches]
    predicted = 0
    for _batch_key, saved in _run_phase(run_batch, items, workers):
        predicted += len(saved)

    leftovers = [
        (tag, seq)
        for tag, seq in candidates
        if not os.path.exists(_candidate_pdb_path(folder_path, tag))
    ]
    message = (
        f"Batched GPU pass done: {predicted} predicted, {len(leftovers)} left for the "
        "per-protein pass."
    )
    print(f"ColabFold remote: {message}")
    _record_remote_info(
        run_id_raw,
        stage_number=16,
        message=message,
        payload={"predicted": predicted, "leftover": len(leftovers)},
    )
    return predicted, leftovers


def _run_phase(process_fn, items, workers):
    """Run process_fn(locus_tag, payload) over `items` (an iterable of
    (locus_tag, payload) pairs) at the given concurrency, sequentially when
    workers == 1. Yields (locus_tag, result) pairs as they complete. A
    raised exception (e.g. strict-mode GPU abort) propagates immediately,
    same as before this was factored out."""
    if workers == 1:
        for locus_tag, payload in items:
            yield locus_tag, process_fn(locus_tag, payload)
        return

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cfold") as ex:
        futures = {
            ex.submit(process_fn, locus_tag, payload): locus_tag for locus_tag, payload in items
        }
        for fut in as_completed(futures):
            yield futures[fut], fut.result()


def _candidate_pdb_path(folder_path, locus_tag):
    return os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af.pdb")


def _format_attempt_error(mode_label, attempt, total_attempts, exc):
    return (f"{mode_label} attempt {attempt}/{total_attempts} failed: {exc}")[:1000]


def _record_retry(run_id_raw, locus_tag, message, payload=None):
    _record_remote_info(
        run_id_raw,
        stage_number=16,
        message=f"{locus_tag}: {message}"[:1000],
        payload={"locus_tag": locus_tag, **dict(payload or {})},
    )


def _run_candidate_attempt(
    config, run_id_raw, folder_path, genome, locus_tag, sequence, mode, fallback_reason
):
    ssh, scp_client, sftp = _open_session_waiting(config)
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
            mode=mode,
            fallback_reason=fallback_reason,
        )
    finally:
        _close_remote_session(ssh, scp_client, sftp)


def _run_batch_attempt(config, run_id_raw, folder_path, genome, entries):
    ssh, scp_client, sftp = _open_session_waiting(config)
    try:
        return _run_remote_colabfold_job(
            ssh=ssh,
            scp_client=scp_client,
            sftp=sftp,
            config=config,
            run_id_raw=run_id_raw,
            folder_path=folder_path,
            genome=genome,
            entries=entries,
            mode="gpu",
            batch=True,
        )
    finally:
        _close_remote_session(ssh, scp_client, sftp)


def _process_candidate_gpu_phase(config, locus_tag, sequence, folder_path, genome, run_id_raw):
    """GPU-only attempt (with retries) for one candidate.

    Returns ``None`` on success. Returns ``("defer", sequence, reason)`` if
    this candidate needs the CPU catch-up pass instead (too long for GPU,
    or every GPU attempt failed) -- never attempts CPU here, see
    run_remote_colabfold's docstring for why. Returns ``("error", message)``
    only in strict mode, where a GPU failure is a hard failure rather than a
    deferral (unchanged from the pre-two-pass behavior)."""
    pdb_path = _candidate_pdb_path(folder_path, locus_tag)
    if os.path.exists(pdb_path):
        return None  # e.g. recovered from an earlier run's batch output

    if config.max_sequence_length > 0 and len(sequence) > config.max_sequence_length:
        return (
            "defer",
            sequence,
            f"length {len(sequence)} aa exceeds GPU limit {config.max_sequence_length} aa",
        )

    gpu_attempts = max(1, config.gpu_retry_attempts)
    last_gpu_exc = None
    for attempt in range(1, gpu_attempts + 1):
        try:
            _run_candidate_attempt(
                config, run_id_raw, folder_path, genome, locus_tag, sequence, "gpu", ""
            )
            if os.path.exists(pdb_path):
                return None
        except Exception as exc:
            last_gpu_exc = exc
            if config.strict_gpu:
                message = (
                    f"Remote ColabFold GPU failed for {locus_tag}; "
                    f"strict mode on, no CPU catch-up. Details: {exc}"
                )[:1000]
                _record_remote_info(
                    run_id_raw, stage_number=16, message=message, payload={"locus_tag": locus_tag}
                )
                return ("error", message)
            _record_retry(
                run_id_raw,
                locus_tag,
                _format_attempt_error("GPU", attempt, gpu_attempts, exc),
                payload={"mode": "gpu", "attempt": attempt, "total_attempts": gpu_attempts},
            )

    return ("defer", sequence, f"remote GPU failure: {last_gpu_exc}")


def _process_candidate_cpu_catchup(
    config, locus_tag, sequence, folder_path, genome, run_id_raw, fallback_reason
):
    """CPU catch-up attempt (with retries) for a candidate the GPU phase
    deferred. Returns ``None`` on success, or a short error string."""
    pdb_path = _candidate_pdb_path(folder_path, locus_tag)
    if os.path.exists(pdb_path):
        return None
    _record_remote_info(
        run_id_raw,
        stage_number=16,
        message=f"CPU catch-up pass starting for {locus_tag} ({fallback_reason}).",
        payload={"locus_tag": locus_tag, "length": len(sequence)},
    )

    last_exc = None
    cpu_attempts = max(1, config.cpu_retry_attempts)
    for attempt in range(1, cpu_attempts + 1):
        try:
            _run_candidate_attempt(
                config, run_id_raw, folder_path, genome, locus_tag, sequence, "cpu", fallback_reason
            )
            if os.path.exists(pdb_path):
                return None
        except Exception as exc:
            last_exc = exc
            _record_retry(
                run_id_raw,
                locus_tag,
                _format_attempt_error("CPU", attempt, cpu_attempts, exc),
                payload={"mode": "cpu", "attempt": attempt, "total_attempts": cpu_attempts},
            )

    return (
        f"Remote ColabFold CPU catch-up failed for {locus_tag} after {cpu_attempts} attempts: "
        f"{last_exc}"
    )[:1000]

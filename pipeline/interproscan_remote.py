import gzip
import os
import shlex
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


def _config_text(cfg_dict, section, option, default=None):
    try:
        value = cfg_dict.get(section, option, fallback=None)
    except Exception:
        value = None
    text = str(value or "").strip()
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


def _record_remote_info(run_id_raw, *, message, payload=None):
    if not run_id_raw or not message:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id_raw),
            stage_number=10,
            app_name="interproscan",
            status="info",
            message=message,
            payload=dict(payload or {}),
        )
    except Exception:
        pass


def _gzip_tsv_output(tsv_path, tsv_gz_path):
    with open(tsv_path, "r", encoding="utf-8") as handle:
        zipped_content = gzip.compress(handle.read().encode("utf-8"))
    with open(tsv_gz_path, "wb") as handle:
        handle.write(zipped_content)


@dataclass
class InterProScanRemoteConfig:
    ssh_rootfolder: str
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_cores: str
    ssh_password: str | None
    ssh_key_filename: str | list[str] | None
    ssh_connect_timeout: int
    remote_poll_seconds: int
    remote_wait_seconds: int
    remote_completion_grace_seconds: int
    conda_prefix: str
    iprscan_install_dir: str
    iprscan_applications: str | None
    slurm_partition: str
    slurm_time: str
    slurm_mem: str


def _build_remote_config(cfg_dict):
    ssh_connect_timeout = _env_int("TPW_INTERPRO_SSH_CONNECT_TIMEOUT_SEC", default=10)
    ssh_port = _env_int("SSH_PORT", default=22)
    ssh_rootfolder = _env_text("SSH_WORKDIR") or _config_text(cfg_dict, "SSH", "WorkingDir")
    ssh_host = _env_text("SSH_HOSTNAME") or _config_text(cfg_dict, "SSH", "HostName")
    ssh_user = _env_text("SSH_USERNAME") or _config_text(cfg_dict, "SSH", "Username")
    ssh_cores = _env_text("SSH_CORES") or _config_text(cfg_dict, "SSH", "Cores")
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
    if not ssh_cores:
        missing.append("SSH_CORES")
    if missing:
        missing_csv = ", ".join(missing)
        raise RuntimeError(
            f"InterProScan remote configuration is incomplete. Set {missing_csv} via environment or pipeline/settings.ini."
        )

    return InterProScanRemoteConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_cores=ssh_cores,
        ssh_password=ssh_password,
        ssh_key_filename=ssh_key_filename,
        ssh_connect_timeout=ssh_connect_timeout,
        remote_poll_seconds=_env_int("TPW_INTERPRO_REMOTE_POLL_SEC", default=30),
        remote_wait_seconds=_env_int("TPW_INTERPRO_REMOTE_WAIT_SEC", default=21600),
        remote_completion_grace_seconds=_env_int(
            "TPW_INTERPRO_REMOTE_COMPLETION_GRACE_SEC",
            default=60,
        ),
        conda_prefix=_env_text("TPW_INTERPRO_CONDA_PREFIX", default="/home/shared/miniconda3.8"),
        iprscan_install_dir=_env_text("TPW_INTERPRO_INSTALL_DIR", default="/grupos/public/iprscan/current"),
        iprscan_applications=_env_text("TPW_INTERPRO_APPLICATIONS", default=None),
        slurm_partition=os.getenv("TPW_INTERPRO_PARTITION", "cpu"),
        slurm_time=os.getenv("TPW_INTERPRO_TIME", "05:00:00"),
        slurm_mem=os.getenv("TPW_INTERPRO_MEM", "32gb"),
    )


def run_remote_interproscan(cfg_dict, folder_path, genome):
    tsv_path = os.path.join(folder_path, genome + ".faa.tsv")
    tsv_gz_path = os.path.join(folder_path, genome + ".faa.tsv.gz")

    # Skip if output already exists (idempotent re-runs after failure at a later stage)
    if os.path.exists(tsv_gz_path) and os.path.getsize(tsv_gz_path) > 0:
        print(f"InterProScan output already exists for {genome}, skipping remote job.")
        return 0

    config = _build_remote_config(cfg_dict)
    _assert_ssh_reachable(
        config.ssh_host,
        config.ssh_port,
        config.ssh_connect_timeout,
    )

    ssh = None
    scp = None
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

        def _run_remote(command):
            stdin, stdout, stderr = ssh.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return exit_code, out, err

        scp = SCPClient(ssh.get_transport())
        sftp = ssh.open_sftp()
        run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
        remote_job_dir = (
            f"{config.ssh_rootfolder.rstrip('/')}/tpw_interpro/{safe_genome}_{run_label}"
        )
        remote_input = f"{remote_job_dir}/{genome}.faa.gz"
        remote_output = f"{remote_job_dir}/{genome}.faa.tsv"
        remote_script = f"{remote_job_dir}/run_interproscan.sh"
        remote_slurm = f"{remote_job_dir}/interproscan.slurm"
        remote_stdout_pattern = f"{remote_job_dir}/slurm-%j.out"
        remote_stderr_pattern = f"{remote_job_dir}/slurm-%j.err"

        mkdir_exit, _, mkdir_err = _run_remote(f"mkdir -p {shlex.quote(remote_job_dir)}")
        if mkdir_exit != 0:
            raise RuntimeError(
                f"Unable to prepare remote InterProScan directory for {genome}: "
                f"{mkdir_err or f'exit status {mkdir_exit}'}"
            )
        scp.put(os.path.join(folder_path, genome + ".faa.gz"), remote_input)
        applications_flag = (
            f"-appl {shlex.quote(config.iprscan_applications)} "
            if config.iprscan_applications
            else ""
        )

        runner_text = "\n".join(
            [
                "#!/bin/bash",
                "set -eo pipefail",
                f'eval "$({config.conda_prefix}/bin/conda shell.bash hook)"',
                "conda activate interproscan",
                "set -u",
                f'JOB_BASE="${{SLURM_TMPDIR:-{remote_job_dir}/slurm_tmp}}"',
                'mkdir -p "$JOB_BASE"',
                f'TMP_ROOT="$(mktemp -d "$JOB_BASE/{safe_genome}_${{SLURM_JOB_ID:-manual}}_XXXXXX")"',
                'trap \'rm -rf "$TMP_ROOT"\' EXIT',
                'mkdir -p "$TMP_ROOT/work" "$TMP_ROOT/out" "$TMP_ROOT/tmp"',
                f'cp {shlex.quote(remote_input)} "$TMP_ROOT/work/{genome}.faa.gz"',
                (
                    f'zcat "$TMP_ROOT/work/{genome}.faa.gz" | '
                    f"{config.iprscan_install_dir}/interproscan.sh --pathways --goterms "
                    f"--cpu {config.ssh_cores} -iprlookup --formats tsv "
                    f"{applications_flag}"
                    f'-T "$TMP_ROOT/tmp" -b "$TMP_ROOT/out/output" -i -'
                ),
                f'cp "$TMP_ROOT/out/output.tsv" {shlex.quote(remote_output)}',
                "",
            ]
        )
        slurm_text = "\n".join(
            [
                "#!/bin/bash",
                f"#SBATCH --job-name=ipr_{safe_genome[:20]}",
                f"#SBATCH -p {config.slurm_partition}",
                f"#SBATCH --cpus-per-task={config.ssh_cores}",
                f"#SBATCH --time={config.slurm_time}",
                f"#SBATCH --mem={config.slurm_mem}",
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
            friendly = classify_slurm_resource_message(details)
            if friendly:
                details = f"{friendly} SLURM response: {details}"
            raise RuntimeError(
                f"Unable to submit remote InterProScan job for {genome}: "
                f"{details}"
            )

        run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()
        job_id = submit_out.split(";")[0].strip()
        if not job_id:
            raise RuntimeError(f"Unable to parse Slurm job id for remote InterProScan on {genome}")
        _record_remote_job(
            run_id_raw,
            job_id=job_id,
            remote_job_dir=remote_job_dir,
        )

        remote_stdout = f"{remote_job_dir}/slurm-{job_id}.out"
        remote_stderr = f"{remote_job_dir}/slurm-{job_id}.err"
        finished = False
        waited_seconds = 0
        last_state = "PENDING"
        completion_seen_at = None
        last_wait_notice = None

        while not finished and waited_seconds <= config.remote_wait_seconds:
            try:
                scp.get(remote_output, folder_path)
                finished = True
                continue
            except Exception:
                pass

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
                    _record_remote_info(
                        run_id_raw,
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
                    details = slurm_err_text or slurm_out_text or state_err or "no remote output captured"
                    friendly = classify_slurm_resource_message(details)
                    if friendly:
                        details = f"{friendly} SLURM details: {details}"
                    raise RuntimeError(
                        f"Remote InterProScan failed for {genome} "
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
                        details = slurm_err_text or slurm_out_text or "no remote output captured"
                        raise RuntimeError(
                            f"Remote InterProScan finished for {genome} but did not produce "
                            f"{genome}.faa.tsv after {config.remote_completion_grace_seconds}s grace period. "
                            f"Details: {details}"
                        )

            print(
                f"InterProScan output for {genome} not available yet. "
                f"Retrying in {config.remote_poll_seconds} seconds..."
            )
            time.sleep(config.remote_poll_seconds)
            waited_seconds += config.remote_poll_seconds

        if not finished:
            raise TimeoutError(
                f"InterProScan output not retrieved for {genome} after "
                f"{waited_seconds} seconds (last remote state: {last_state})"
            )

        _gzip_tsv_output(tsv_path, tsv_gz_path)
        return 0
    finally:
        if scp is not None:
            try:
                scp.close()
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

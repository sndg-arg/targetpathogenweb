import os
import shlex
import socket
import time
from dataclasses import dataclass
from datetime import datetime

import paramiko


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
        expanded = [os.path.expanduser(path) for path in identity_files]
        resolved["key_filename"] = expanded if len(expanded) > 1 else expanded[0]
    return resolved


def _assert_ssh_reachable(host, port, timeout_seconds):
    probe = socket.socket()
    probe.settimeout(timeout_seconds)
    try:
        probe.connect((host, int(port or 22)))
    finally:
        probe.close()


@dataclass
class RemoteShellConfig:
    ssh_rootfolder: str
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_password: str | None
    ssh_key_filename: str | list[str] | None
    ssh_connect_timeout: int
    poll_seconds: int
    wait_seconds: int
    partition: str
    time_limit: str
    mem: str
    cpus_per_task: int
    exclude: str


def _build_config(cfg_dict, prefix):
    ssh_port = _env_int("SSH_PORT", default=22)
    ssh_rootfolder = _env_text("SSH_WORKDIR") or _config_text(cfg_dict, "SSH", "WorkingDir")
    ssh_host = _env_text("SSH_HOSTNAME") or _config_text(cfg_dict, "SSH", "HostName")
    ssh_user = _env_text("SSH_USERNAME") or _config_text(cfg_dict, "SSH", "Username")
    ssh_options = _resolve_ssh_options(ssh_host, user=ssh_user, port=ssh_port)
    ssh_host = ssh_options["host"]
    ssh_user = ssh_options["user"]
    ssh_port = ssh_options["port"]

    missing = []
    if not ssh_rootfolder:
        missing.append("SSH_WORKDIR")
    if not ssh_host:
        missing.append("SSH_HOSTNAME")
    if not ssh_user:
        missing.append("SSH_USERNAME")
    if missing:
        raise RuntimeError(
            f"Remote SLURM configuration is incomplete. Set {', '.join(missing)}."
        )

    return RemoteShellConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_password=_env_text("SSH_PASSWORD") or _config_text(cfg_dict, "SSH", "Password"),
        ssh_key_filename=ssh_options["key_filename"],
        ssh_connect_timeout=_env_int(f"{prefix}_SSH_CONNECT_TIMEOUT_SEC", default=10),
        poll_seconds=_env_int(f"{prefix}_REMOTE_POLL_SEC", default=60),
        wait_seconds=_env_int(f"{prefix}_REMOTE_WAIT_SEC", default=172800),
        partition=_env_text(f"{prefix}_SLURM_PARTITION", default="cpu"),
        time_limit=_env_text(f"{prefix}_SLURM_TIME", default="24:00:00"),
        mem=_env_text(f"{prefix}_SLURM_MEM", default="32G"),
        cpus_per_task=_env_int(f"{prefix}_SLURM_CPUS", default=8),
        exclude=os.getenv(f"{prefix}_SLURM_EXCLUDE", "").strip(),
    )


def _remote_exec(ssh, command):
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def run_remote_shell_job(cfg_dict, *, env_prefix, job_name, command, stage_number=None):
    config = _build_config(cfg_dict, env_prefix)
    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_job = "".join(c if c.isalnum() or c in "._-" else "_" for c in job_name)
    remote_job_dir = f"{config.ssh_rootfolder.rstrip('/')}/tpw_slurm/{safe_job}_{timestamp}"
    script_path = f"{remote_job_dir}/job.sh"
    stdout_path = f"{remote_job_dir}/slurm.out"
    stderr_path = f"{remote_job_dir}/slurm.err"

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
    try:
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

        exit_code, _out, err = _remote_exec(ssh, f"mkdir -p {shlex.quote(remote_job_dir)}")
        if exit_code != 0:
            raise RuntimeError(f"Unable to create remote job dir: {err}")

        sbatch_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={safe_job[:32]}",
            f"#SBATCH --partition={config.partition}",
            f"#SBATCH --time={config.time_limit}",
            f"#SBATCH --mem={config.mem}",
            f"#SBATCH --cpus-per-task={config.cpus_per_task}",
            f"#SBATCH --output={stdout_path}",
            f"#SBATCH --error={stderr_path}",
        ]
        if config.exclude:
            sbatch_lines.append(f"#SBATCH --exclude={config.exclude}")
        sbatch_lines.extend(
            [
                "set -euo pipefail",
                "date",
                command,
                "date",
            ]
        )
        script = "\n".join(sbatch_lines) + "\n"
        exit_code, _out, err = _remote_exec(
            ssh,
            f"cat > {shlex.quote(script_path)} <<'EOF'\n{script}\nEOF\nchmod +x {shlex.quote(script_path)}",
        )
        if exit_code != 0:
            raise RuntimeError(f"Unable to write remote job script: {err}")

        exit_code, out, err = _remote_exec(
            ssh,
            f"cd {shlex.quote(remote_job_dir)} && sbatch --parsable {shlex.quote(script_path)}",
        )
        if exit_code != 0:
            raise RuntimeError(f"sbatch failed: {err or out}")
        job_id = out.strip().split(";")[0]
        if not job_id:
            raise RuntimeError(f"Unable to parse sbatch job id from: {out}")
        print(f"{job_name}: submitted SLURM job {job_id} in {remote_job_dir}")

        deadline = time.time() + config.wait_seconds
        while time.time() < deadline:
            exit_code, state, _err = _remote_exec(
                ssh,
                f"sacct -j {shlex.quote(job_id)} --format=State --noheader | head -1 | awk '{{print $1}}'",
            )
            state = state.strip()
            if state.startswith("COMPLETED"):
                print(f"{job_name}: SLURM job {job_id} completed")
                return 0
            if any(state.startswith(prefix) for prefix in REMOTE_FAILURE_PREFIXES):
                _code, tail_out, _ = _remote_exec(
                    ssh,
                    f"tail -100 {shlex.quote(stdout_path)} {shlex.quote(stderr_path)} 2>/dev/null",
                )
                raise RuntimeError(
                    f"{job_name}: SLURM job {job_id} ended with state {state}. {tail_out[-2000:]}"
                )
            time.sleep(config.poll_seconds)

        raise TimeoutError(
            f"{job_name}: timed out waiting for SLURM job {job_id} after {config.wait_seconds}s"
        )
    finally:
        ssh.close()

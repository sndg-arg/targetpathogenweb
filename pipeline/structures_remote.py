"""
Run structure pocket prediction on a remote SLURM CPU node via SSH.

Stage 17 is different from generic remote shell stages because the TPW database
lives in the web stack, while FPocket/P2Rank must run on compute nodes. This
wrapper stages curated/local PDB files to the cluster, runs FPocket and P2Rank
inside one SLURM job, pulls only the generated outputs back, and then performs
the TPW JSON conversion/import locally.
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime

import paramiko
from scp import SCPClient

from pipeline_commands import (
    fpocket2json_cmd,
    load_af_model_cmd,
    load_p2pocket_cmd,
    load_pocket_cmd,
    p2rank2json_cmd,
)


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
        with open(config_path, encoding="utf-8") as handle:
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


def _assert_ssh_reachable(host, port, timeout):
    probe = socket.socket()
    probe.settimeout(timeout)
    try:
        probe.connect((host, int(port or 22)))
    finally:
        probe.close()


def _record_event(run_id_raw, *, status, message, payload=None):
    if not run_id_raw or not message:
        return
    try:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id_raw),
            stage_number=17,
            app_name="structures_remote",
            status=status,
            message=message,
            payload=dict(payload or {}),
        )
    except Exception:
        pass


@dataclass
class StructuresRemoteConfig:
    ssh_rootfolder: str
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_password: str | None
    ssh_key_filename: str | list[str] | None
    ssh_connect_timeout: int
    remote_poll_seconds: int
    remote_wait_seconds: int
    slurm_partition: str
    slurm_time: str
    slurm_mem: str
    slurm_cpus_per_task: int
    slurm_exclude: str
    remote_setup: str
    fpocket_bin: str
    p2rank_bin: str


def _build_structures_config(cfg_dict):
    ssh_connect_timeout = _env_int("TPW_STRUCTURES_SSH_CONNECT_TIMEOUT_SEC", default=10)
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
            "Structure remote configuration is incomplete. "
            f"Set {', '.join(missing)} via environment or pipeline/settings.ini."
        )

    return StructuresRemoteConfig(
        ssh_rootfolder=ssh_rootfolder,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_password=ssh_password,
        ssh_key_filename=ssh_key_filename,
        ssh_connect_timeout=ssh_connect_timeout,
        remote_poll_seconds=_env_int("TPW_STRUCTURES_REMOTE_POLL_SEC", default=60),
        remote_wait_seconds=_env_int("TPW_STRUCTURES_REMOTE_WAIT_SEC", default=259200),
        slurm_partition=_env_text("TPW_STRUCTURES_SLURM_PARTITION", default="cpu"),
        slurm_time=_env_text("TPW_STRUCTURES_SLURM_TIME", default="48:00:00"),
        slurm_mem=_env_text("TPW_STRUCTURES_SLURM_MEM", default="32G"),
        slurm_cpus_per_task=_env_int("TPW_STRUCTURES_SLURM_CPUS", default=8),
        slurm_exclude=os.getenv("TPW_STRUCTURES_SLURM_EXCLUDE", "").strip(),
        remote_setup=os.getenv("TPW_STRUCTURES_REMOTE_SETUP", "").strip(),
        fpocket_bin=_env_text("TPW_STRUCTURES_FPOCKET_BIN", default="fpocket"),
        p2rank_bin=_env_text("TPW_STRUCTURES_P2RANK_BIN", default="prank"),
    )


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
    _stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def _data_dir(working_dir):
    return os.path.join(working_dir, "data")


def _safe_label(value):
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in value)


def _protein_pdbs(folder_path):
    alphafold_dir = os.path.join(folder_path, "alphafold")
    if not os.path.isdir(alphafold_dir):
        return []
    proteins = []
    for locus_tag in sorted(os.listdir(alphafold_dir)):
        pdb_path = os.path.join(alphafold_dir, locus_tag, f"{locus_tag}_af.pdb")
        if os.path.exists(pdb_path) and os.path.getsize(pdb_path) > 0:
            proteins.append((locus_tag, pdb_path))
    return proteins


def _build_input_tar(local_tar, proteins):
    with tarfile.open(local_tar, "w") as tar:
        for locus_tag, pdb_path in proteins:
            tar.add(pdb_path, arcname=f"alphafold/{locus_tag}/{locus_tag}_af.pdb")


def _build_slurm_script(config, remote_input_tar, remote_output_tar, remote_workdir):
    setup_lines = [config.remote_setup] if config.remote_setup else []
    return "\n".join(
        [
            "#!/bin/bash",
            "#SBATCH --job-name=tpw_struct",
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
            *setup_lines,
            f"FPOCKET_BIN={shlex.quote(config.fpocket_bin)}",
            f"P2RANK_BIN={shlex.quote(config.p2rank_bin)}",
            f"INPUT_TAR={shlex.quote(remote_input_tar)}",
            f"OUTPUT_TAR={shlex.quote(remote_output_tar)}",
            f"REMOTE_WORKDIR={shlex.quote(remote_workdir)}",
            'THREADS="${SLURM_CPUS_PER_TASK:-1}"',
            'WORK_ROOT="${REMOTE_WORKDIR}/work"',
            'OUTPUT_ROOT="${REMOTE_WORKDIR}/output"',
            'FAILURES="${REMOTE_WORKDIR}/failures.tsv"',
            'SUMMARY="${REMOTE_WORKDIR}/summary.tsv"',
            'DONE="${REMOTE_WORKDIR}/DONE"',
            'rm -rf "${WORK_ROOT}" "${OUTPUT_ROOT}"',
            'mkdir -p "${WORK_ROOT}" "${OUTPUT_ROOT}/alphafold"',
            ': > "${FAILURES}"',
            'printf "metric\\tvalue\\n" > "${SUMMARY}"',
            'if ! command -v "${FPOCKET_BIN}" >/dev/null 2>&1; then',
            '  printf "setup\\tfpocket\\tmissing executable: %s\\n" "${FPOCKET_BIN}" >> "${FAILURES}"',
            "fi",
            'if ! command -v "${P2RANK_BIN}" >/dev/null 2>&1; then',
            '  printf "setup\\tp2rank\\tmissing executable: %s\\n" "${P2RANK_BIN}" >> "${FAILURES}"',
            "fi",
            'if [ -s "${FAILURES}" ]; then',
            '  tar cf "${OUTPUT_TAR}" -C "${REMOTE_WORKDIR}" output failures.tsv summary.tsv',
            '  touch "${DONE}"',
            "  exit 0",
            "fi",
            'tar xf "${INPUT_TAR}" -C "${WORK_ROOT}"',
            'total=0; fpocket_ok=0; p2rank_ok=0',
            'while IFS= read -r -d "" pdb; do',
            '  total=$((total + 1))',
            '  locus="$(basename "$(dirname "${pdb}")")"',
            '  locus_dir="$(dirname "${pdb}")"',
            '  out_locus="${OUTPUT_ROOT}/alphafold/${locus}"',
            '  mkdir -p "${out_locus}"',
            '  echo "[$(date)] ${locus}"',
            '  if (cd "${locus_dir}" && "${FPOCKET_BIN}" -f "${locus}_af.pdb"); then',
            '    fpocket_ok=$((fpocket_ok + 1))',
            '    if [ -d "${locus_dir}/${locus}_af_out" ]; then',
            '      cp -a "${locus_dir}/${locus}_af_out" "${out_locus}/"',
            "    fi",
            "  else",
            '    printf "%s\\tfpocket\\tfailed\\n" "${locus}" >> "${FAILURES}"',
            "  fi",
            '  p2rank_dir="${locus_dir}/p2rank"',
            '  mkdir -p "${p2rank_dir}"',
            '  if "${P2RANK_BIN}" predict -f "${pdb}" -o "${p2rank_dir}" -threads "${THREADS}"; then',
            '    p2rank_ok=$((p2rank_ok + 1))',
            '    cp -a "${p2rank_dir}" "${out_locus}/"',
            "  else",
            '    printf "%s\\tp2rank\\tfailed\\n" "${locus}" >> "${FAILURES}"',
            "  fi",
            'done < <(find "${WORK_ROOT}/alphafold" -mindepth 2 -maxdepth 2 -name "*_af.pdb" -print0)',
            'printf "proteins\\t%s\\n" "${total}" >> "${SUMMARY}"',
            'printf "fpocket_ok\\t%s\\n" "${fpocket_ok}" >> "${SUMMARY}"',
            'printf "p2rank_ok\\t%s\\n" "${p2rank_ok}" >> "${SUMMARY}"',
            'tar cf "${OUTPUT_TAR}" -C "${REMOTE_WORKDIR}" output failures.tsv summary.tsv',
            'touch "${DONE}"',
            "",
        ]
    )


def _wait_for_job(ssh, config, job_id, remote_workdir, remote_done):
    waited = 0
    last_state = "PENDING"
    while waited <= config.remote_wait_seconds:
        done_exit, _, _ = _exec_remote(ssh, f"test -f {shlex.quote(remote_done)}")
        if done_exit == 0:
            return

        _, state_out, _ = _exec_remote(
            ssh,
            f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n | head -n 1",
        )
        line = state_out.splitlines()[0].strip() if state_out else ""
        parts = line.split("|") if line else []
        if len(parts) >= 3:
            _, state, exit_code = parts[:3]
            last_state = state or last_state
            if last_state.upper().startswith(REMOTE_FAILURE_PREFIXES):
                _, slurm_out, _ = _exec_remote(
                    ssh,
                    f"tail -n 120 {shlex.quote(remote_workdir)}/slurm-{job_id}.out 2>/dev/null || true",
                )
                _, slurm_err, _ = _exec_remote(
                    ssh,
                    f"tail -n 120 {shlex.quote(remote_workdir)}/slurm-{job_id}.err 2>/dev/null || true",
                )
                raise RuntimeError(
                    f"Remote structures job failed ({state} / {exit_code}): "
                    f"{slurm_err or slurm_out or 'no remote output'}"
                )

        print(f"structures remote: waiting (state={last_state}, {waited}s elapsed)")
        time.sleep(config.remote_poll_seconds)
        waited += config.remote_poll_seconds

    raise TimeoutError(f"Structures job did not finish in {waited}s (last state: {last_state})")


def _existing_loaded_structures(genome):
    try:
        from bioseq.models.Biodatabase import Biodatabase
        from tpweb.models.BioentryStructure import BioentryStructure

        db_name = genome + Biodatabase.PROT_POSTFIX
        return set(
            BioentryStructure.objects.filter(bioentry__biodatabase__name=db_name)
            .values_list("bioentry__accession", flat=True)
            .distinct()
        )
    except Exception:
        return set()


def _copy_remote_outputs(extract_dir, folder_path, genome, working_dir):
    from bioseq.io.SeqStore import SeqStore

    data_dir = _data_dir(working_dir)
    seqstore = SeqStore(data_dir)
    extracted_alphafold = os.path.join(extract_dir, "output", "alphafold")
    if not os.path.isdir(extracted_alphafold):
        return []

    copied = []
    for locus_tag in sorted(os.listdir(extracted_alphafold)):
        remote_locus_dir = os.path.join(extracted_alphafold, locus_tag)
        local_locus_dir = os.path.join(folder_path, "alphafold", locus_tag)
        os.makedirs(local_locus_dir, exist_ok=True)

        remote_fpocket = os.path.join(remote_locus_dir, f"{locus_tag}_af_out")
        local_fpocket = os.path.join(local_locus_dir, f"{locus_tag}_af_out")
        if os.path.isdir(remote_fpocket):
            shutil.rmtree(local_fpocket, ignore_errors=True)
            shutil.copytree(remote_fpocket, local_fpocket)

        remote_p2rank = os.path.join(remote_locus_dir, "p2rank")
        if os.path.isdir(remote_p2rank):
            local_p2rank = seqstore.p2rank_folder(genome, locus_tag)
            shutil.rmtree(local_p2rank, ignore_errors=True)
            os.makedirs(os.path.dirname(local_p2rank), exist_ok=True)
            shutil.copytree(remote_p2rank, local_p2rank)

        copied.append(locus_tag)
    return copied


def _run_local_command(command, label):
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or "")[-1200:]
        raise RuntimeError(f"{label} failed (rc={result.returncode}): {error_msg}")


def _postprocess_outputs(locus_tags, genome, working_dir, folder_path):
    loaded_structures = _existing_loaded_structures(genome)
    errors = []
    fpocket_loaded = 0
    p2rank_loaded = 0

    for index, locus_tag in enumerate(locus_tags, start=1):
        try:
            if locus_tag not in loaded_structures:
                _run_local_command(
                    load_af_model_cmd(locus_tag, working_dir, folder_path),
                    f"load_af_model {locus_tag}",
                )

            _run_local_command(
                fpocket2json_cmd(folder_path, locus_tag),
                f"fpocket2json {locus_tag}",
            )
            fpocket_json = os.path.join(
                folder_path,
                "alphafold",
                locus_tag,
                f"{locus_tag}_af_out",
                "fpocket.json.gz",
            )
            if os.path.exists(fpocket_json):
                _run_local_command(
                    load_pocket_cmd(folder_path, locus_tag, working_dir),
                    f"load_fpocket {locus_tag}",
                )
                fpocket_loaded += 1

            _run_local_command(
                p2rank2json_cmd(genome, locus_tag, working_dir),
                f"p2rank2json {locus_tag}",
            )
            _run_local_command(
                load_p2pocket_cmd(genome, locus_tag, working_dir),
                f"load_p2pocket {locus_tag}",
            )
            p2rank_loaded += 1
        except Exception as exc:
            errors.append((locus_tag, str(exc)))

        if index == 1 or index % 100 == 0 or index == len(locus_tags):
            print(
                "structures remote: local import "
                f"{index}/{len(locus_tags)} "
                f"(fpocket={fpocket_loaded}, p2rank={p2rank_loaded}, failed={len(errors)})"
            )

    return fpocket_loaded, p2rank_loaded, errors


def _read_remote_failures(extract_dir):
    failures_path = os.path.join(extract_dir, "failures.tsv")
    if not os.path.exists(failures_path):
        return []
    with open(failures_path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def _read_remote_summary(extract_dir):
    summary_path = os.path.join(extract_dir, "summary.tsv")
    if not os.path.exists(summary_path):
        return {}
    summary = {}
    with open(summary_path, encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            key, _, value = line.rstrip("\n").partition("\t")
            if key:
                summary[key] = value
    return summary


def run_remote_structures(cfg_dict, folder_path, genome, working_dir):
    config = _build_structures_config(cfg_dict)
    run_id_raw = str(os.getenv("TPW_PIPELINE_RUN_ID") or "").strip()

    proteins = _protein_pdbs(folder_path)
    if not proteins:
        print("No protein structures found to process remotely.")
        return 0

    local_stage_dir = os.path.join(folder_path, "structures_remote")
    os.makedirs(local_stage_dir, exist_ok=True)

    safe_genome = _safe_label(genome)
    run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    local_input_tar = os.path.join(local_stage_dir, f"structures_input_{run_label}.tar")
    local_output_tar = os.path.join(local_stage_dir, f"structures_output_{run_label}.tar")
    local_extract_dir = os.path.join(local_stage_dir, f"structures_output_{run_label}")

    print(f"structures remote: packaging {len(proteins)} PDB files")
    _build_input_tar(local_input_tar, proteins)

    _assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)

    remote_workdir = f"{config.ssh_rootfolder.rstrip('/')}/tpw_structures/{safe_genome}_{run_label}"
    remote_input_tar = f"{remote_workdir}/structures_input.tar"
    remote_output_tar = f"{remote_workdir}/structures_output.tar"
    remote_slurm = f"{remote_workdir}/structures_batch.slurm"
    remote_done = f"{remote_workdir}/DONE"

    ssh = None
    scp_client = None
    sftp = None
    job_id = None
    finished = False
    try:
        ssh, scp_client, sftp = _open_remote_session(config)
        mk_exit, _, mk_err = _exec_remote(ssh, f"mkdir -p {shlex.quote(remote_workdir)}")
        if mk_exit != 0:
            raise RuntimeError(f"Cannot create remote dir {remote_workdir}: {mk_err}")

        print(f"structures remote: uploading input tar to {remote_workdir}")
        scp_client.put(local_input_tar, remote_input_tar)
        os.remove(local_input_tar)

        slurm_text = _build_slurm_script(
            config,
            remote_input_tar,
            remote_output_tar,
            remote_workdir,
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
            raise RuntimeError(f"Cannot parse structures SLURM job id from: {sub_out!r}")

        print(f"structures remote: submitted SLURM job {job_id}")
        _record_event(
            run_id_raw,
            status="info",
            message=f"Submitted remote structures job {job_id} for {genome}",
            payload={"job_id": job_id, "remote_workdir": remote_workdir, "genome": genome},
        )

        _wait_for_job(ssh, config, job_id, remote_workdir, remote_done)
        finished = True

        print("structures remote: pulling FPocket/P2Rank outputs")
        scp_client.get(remote_output_tar, local_output_tar)
    finally:
        if not finished and job_id and ssh is not None:
            try:
                _exec_remote(ssh, f"scancel {shlex.quote(job_id)} 2>/dev/null || true")
                print(f"structures remote: cancelled orphan SLURM job {job_id}")
            except Exception:
                pass
        _close_remote_session(ssh, scp_client, sftp)

    shutil.rmtree(local_extract_dir, ignore_errors=True)
    os.makedirs(local_extract_dir, exist_ok=True)
    with tarfile.open(local_output_tar, "r") as tar:
        tar.extractall(local_extract_dir)
    os.remove(local_output_tar)

    remote_summary = _read_remote_summary(local_extract_dir)
    remote_failures = _read_remote_failures(local_extract_dir)
    print(f"structures remote: remote summary {remote_summary}")
    if remote_failures:
        print(f"structures remote: remote failures detected ({len(remote_failures)})")

    copied_loci = _copy_remote_outputs(local_extract_dir, folder_path, genome, working_dir)
    print(f"structures remote: copied outputs for {len(copied_loci)} proteins")

    fpocket_loaded, p2rank_loaded, local_errors = _postprocess_outputs(
        copied_loci,
        genome,
        working_dir,
        folder_path,
    )
    shutil.rmtree(local_extract_dir, ignore_errors=True)

    print(
        "structures remote done: "
        f"fpocket_loaded={fpocket_loaded}, "
        f"p2rank_loaded={p2rank_loaded}, "
        f"remote_failures={len(remote_failures)}, "
        f"local_failures={len(local_errors)}"
    )

    if remote_failures or local_errors:
        details = []
        details.extend(remote_failures[:10])
        details.extend(f"{locus}: {message}" for locus, message in local_errors[:10])
        raise RuntimeError(
            "Remote structures stage finished with failures: "
            + "; ".join(details)
            + ("; ..." if len(remote_failures) + len(local_errors) > 10 else "")
        )

    _record_event(
        run_id_raw,
        status="info",
        message=f"Remote structures stage complete (job {job_id})",
        payload={
            "job_id": job_id,
            "genome": genome,
            "fpocket_loaded": fpocket_loaded,
            "p2rank_loaded": p2rank_loaded,
        },
    )
    return 0

"""Stage 20: stage FASTA to SLURM, run PSORTb, validate and publish its TSV."""

import gzip
import os
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from psort_worker import read_fasta, validate_psort_file


def _record_event(message, payload):
    run_id = os.getenv("TPW_PIPELINE_RUN_ID", "").strip()
    if run_id:
        from tpweb.services.pipeline_runs import record_pipeline_stage_event

        record_pipeline_stage_event(
            int(run_id),
            stage_number=20,
            app_name="psort_remote",
            status="info",
            message=message,
            payload=payload,
        )


def _build_script(config, workdir, gram):
    quote = shlex.quote
    runtime = os.getenv("TPW_PSORT_APPTAINER_BIN") or (
        config.ssh_rootfolder.rstrip("/") + "/work/conda_envs/tpw_apptainer/bin/apptainer"
    )
    image = os.getenv("TPW_PSORT_IMAGE") or (
        config.ssh_rootfolder.rstrip("/") + "/tpw_images/psortb_1.0.2.sif"
    )
    python = os.getenv("TPW_PSORT_REMOTE_PYTHON") or (
        config.ssh_rootfolder.rstrip("/") + "/work/conda_envs/tpw_apptainer/bin/python"
    )
    batch_size = int(os.getenv("TPW_PSORT_BATCH_SIZE") or "50")
    timeout = int(os.getenv("TPW_PSORT_BATCH_TIMEOUT_SEC") or "1800")
    if gram not in {"n", "p", "a"} or min(batch_size, timeout, config.cpus_per_task) < 1:
        raise ValueError("Invalid PSORT gram type or worker/batch/timeout limit")
    command = [
        python,
        "-u",
        workdir + "/psort_worker.py",
        "--fasta",
        workdir + "/input.faa",
        "--output",
        workdir + "/psort.tsv",
        "--cache",
        config.ssh_rootfolder.rstrip("/") + "/tpw_psort/cache",
        "--runtime",
        runtime,
        "--image",
        image,
        "--gram",
        gram,
        "--workers",
        str(config.cpus_per_task),
        "--batch-size",
        str(batch_size),
        "--timeout",
        str(timeout),
    ]
    return "\n".join(
        [
            "#!/bin/bash",
            "#SBATCH --job-name=tpw_psort",
            "#SBATCH --partition=" + config.partition,
            "#SBATCH --time=" + config.time_limit,
            "#SBATCH --mem=" + config.mem,
            "#SBATCH --cpus-per-task=" + str(config.cpus_per_task),
            "#SBATCH --output=" + workdir + "/slurm.out",
            "#SBATCH --error=" + workdir + "/slurm.err",
            *(("#SBATCH --exclude=" + config.exclude,) if config.exclude else ()),
            "set -eo pipefail",
            os.getenv("TPW_PSORT_REMOTE_SETUP", ""),
            "set -u",
            "cd " + quote(workdir),
            "command -v " + quote(runtime) + " >/dev/null || { "
            "echo 'PSORT runtime missing; run scripts/cluster/setup_psort.sh via sbatch' >&2; exit 1; }",
            "test -s " + quote(image) + " || { echo 'PSORT SIF image missing' >&2; exit 1; }",
            " ".join(map(quote, command)),
            "touch DONE",
            "",
        ]
    )


def _wait_for_job(ssh, remote, config, job_id, workdir):
    deadline = time.monotonic() + config.wait_seconds
    while time.monotonic() < deadline:
        code, out, err = remote._exec_remote(
            ssh, f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n"
        )
        if code:
            raise RuntimeError("Cannot query PSORT SLURM job: " + (err or out))
        state = "UNKNOWN"
        for line in out.splitlines():
            fields = line.split("|")
            if len(fields) >= 3 and fields[0] == job_id:
                state, exit_code = fields[1:3]
                if state == "COMPLETED" and exit_code == "0:0":
                    done, _, _ = remote._exec_remote(
                        ssh, "test -f " + shlex.quote(workdir + "/DONE")
                    )
                    if done == 0:
                        return
                    raise RuntimeError("PSORT job completed without validated output marker")
                if state.startswith(remote.REMOTE_FAILURE_PREFIXES) or state == "COMPLETED":
                    _, logs, _ = remote._exec_remote(
                        ssh,
                        "tail -30 {} {}".format(
                            shlex.quote(workdir + "/slurm.out"), shlex.quote(workdir + "/slurm.err")
                        ),
                    )
                    raise RuntimeError(
                        f"PSORT job {job_id}: {state} / {exit_code} in {workdir}\n{logs[-3000:]}"
                    )
        print(f"PSORT remote: job {job_id} state={state}", flush=True)
        time.sleep(config.poll_seconds)
    raise TimeoutError(f"PSORT job {job_id} exceeded {config.wait_seconds}s; logs: {workdir}")


def run_remote_psort(cfg_dict, folder_path, genome, gram):
    import slurm_remote_command as remote

    config = remote._build_config(cfg_dict, "TPW_PSORT")
    stage_dir = Path(folder_path) / "psort_remote"
    stage_dir.mkdir(parents=True, exist_ok=True)
    fasta = Path(folder_path) / (genome + ".faa")
    compressed = Path(str(fasta) + ".gz")
    if not fasta.exists() and compressed.exists():
        fasta = stage_dir / "input.faa"
        with gzip.open(compressed, "rb") as source, fasta.open("wb") as target:
            shutil.copyfileobj(source, target)
    read_fasta(fasta)
    safe_genome = "".join(c if c.isalnum() or c in "._-" else "_" for c in genome)
    workdir = "{}/tpw_psort/{}_{}".format(
        config.ssh_rootfolder.rstrip("/"), safe_genome, uuid.uuid4().hex[:12]
    )
    script = _build_script(config, workdir, gram)
    remote._assert_ssh_reachable(config.ssh_host, config.ssh_port, config.ssh_connect_timeout)
    ssh, scp, sftp = remote._open_remote_session(config)
    job_id = None
    finished = False
    candidate = None
    try:
        code, out, err = remote._exec_remote(ssh, "mkdir -p " + shlex.quote(workdir))
        if code:
            raise RuntimeError("Cannot create PSORT workdir: " + (err or out))
        scp.put(str(fasta), workdir + "/input.faa")
        scp.put(str(Path(__file__).with_name("psort_worker.py")), workdir + "/psort_worker.py")
        with sftp.file(workdir + "/job.sh", "w") as handle:
            handle.write(script)
        code, out, err = remote._exec_remote(
            ssh, "sbatch --parsable " + shlex.quote(workdir + "/job.sh")
        )
        if code:
            raise RuntimeError("Cannot submit PSORT job: " + (err or out))
        job_id = out.split(";")[0].strip()
        if not job_id.isdigit():
            job_id = None
            raise RuntimeError("Invalid PSORT SLURM job ID: " + out)
        print(f"PSORT remote: submitted job {job_id} in {workdir}", flush=True)
        _record_event(
            "Submitted remote PSORT job " + job_id, {"job_id": job_id, "remote_workdir": workdir}
        )
        _wait_for_job(ssh, remote, config, job_id, workdir)
        finished = True
        with tempfile.NamedTemporaryFile(dir=folder_path, delete=False) as handle:
            candidate = handle.name
        scp.get(workdir + "/psort.tsv", candidate)
        rows = validate_psort_file(candidate, fasta)
        os.chmod(candidate, 0o644)
        os.replace(candidate, str(Path(folder_path) / "psort.tsv"))
        candidate = None
        print(f"PSORT remote: validated {len(rows)} predictions", flush=True)
        return 0
    finally:
        try:
            if job_id and not finished:
                remote._exec_remote(ssh, "scancel " + shlex.quote(job_id))
        finally:
            remote._close_remote_session(ssh, scp, sftp)
            if candidate and os.path.exists(candidate):
                os.unlink(candidate)

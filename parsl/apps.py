import parsl
from parsl import python_app, bash_app, join_app
import time
import os
import socket
from parsl.data_provider.files import File


def _flag_enabled(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _assert_ssh_reachable(host, port, timeout_seconds):
    probe = socket.socket()
    probe.settimeout(timeout_seconds)
    try:
        probe.connect((host, port))
    finally:
        probe.close()


@python_app(executors=['local_executor'])
def clear_folder(folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os, shutil
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)
    return

@bash_app(executors=["local_executor"])
def download_gbk(working_dir, genome, target_accession=None, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    command = f"python {working_dir}/manage.py tpweb_download_gbk {genome} --datadir {working_dir}/data"
    if target_accession:
        command += f" --target-accession {target_accession}"
    return command

@bash_app(executors=["local_executor"])
def test_gbk(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py tpweb_test_gbk --datadir ../data --target-accession {genome}"

@bash_app(executors=["local_executor"])
def custom_gbk(working_dir, genome, custom,inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python {working_dir}/manage.py custom_gbk {genome} --datadir ../data --custom {custom}"

@bash_app(executors=["local_executor"])
def load_gbk(working_dir, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz")
    return f"python {working_dir}/manage.py load_gbk {gbk_path} --overwrite --accession {genome} --datadir {working_dir}/data"


@bash_app(executors=["local_executor"])
def index_genome_db(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py index_genome_db {genome} --datadir {working_dir}/data"


@bash_app(executors=["local_executor"])
def index_genome_seq(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py index_genome_seq_clean {genome} --datadir {working_dir}/data"


@bash_app(executors=["local_executor"])
def seed_test_demo_annotations(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py seed_test_demo_annotations {genome}"


@python_app(executors=['local_executor'])
def interproscan(cfg_dict, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import paramiko
    import os
    import time
    import gzip
    import shlex
    from datetime import datetime
    from scp import SCPClient
    from config import TargetConfig
    tsv_path = os.path.join(folder_path, genome + ".faa.tsv")
    tsv_gz_path = os.path.join(folder_path, genome + ".faa.tsv.gz")
    local_profile = os.getenv("TPW_PROFILE", "").strip().lower() == "local"
    allow_local_fallback = local_profile and _flag_enabled("TPW_INTERPRO_LOCAL_FALLBACK", default=True)
    ssh_connect_timeout = _env_int("TPW_INTERPRO_SSH_CONNECT_TIMEOUT_SEC", default=10)
    ssh_port = _env_int("SSH_PORT", default=22)
    remote_poll_seconds = _env_int("TPW_INTERPRO_REMOTE_POLL_SEC", default=30)
    remote_wait_seconds = _env_int(
        "TPW_INTERPRO_REMOTE_WAIT_SEC",
        default=1800 if allow_local_fallback else 21600,
    )
    slurm_partition = os.getenv("TPW_INTERPRO_PARTITION", "cpu")
    slurm_time = os.getenv("TPW_INTERPRO_TIME", "05:00:00")
    slurm_mem = os.getenv("TPW_INTERPRO_MEM", "32gb")

    ssh = None
    scp = None
    sftp = None
    try:
        def _run_remote(command):
            stdin, stdout, stderr = ssh.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return exit_code, out, err

        ssh = paramiko.SSHClient()
        ssh_rootfolder = os.getenv("SSH_WORKDIR") or cfg_dict.get("SSH", "WorkingDir")
        ssh_host = os.getenv("SSH_HOSTNAME") or cfg_dict.get("SSH", "HostName")
        ssh_user = os.getenv("SSH_USERNAME") or cfg_dict.get("SSH", "Username")
        ssh_cores = os.getenv("SSH_CORES") or cfg_dict.get("SSH", "Cores")
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pwd = os.getenv("SSH_PASSWORD")
        if pwd is None:
            pwd = cfg_dict.get("SSH", "Password", fallback=None)
        if pwd == "":
            pwd = None  # allow agent/key auth only
        # In local profile, fail fast when the remote cluster is not reachable so the
        # pipeline can use the empty-output fallback instead of hanging indefinitely.
        if allow_local_fallback:
            _assert_ssh_reachable(ssh_host, ssh_port, ssh_connect_timeout)
        ssh.connect(
            ssh_host,
            port=ssh_port,
            username=ssh_user,
            password=pwd,
            timeout=ssh_connect_timeout,
            banner_timeout=ssh_connect_timeout,
            auth_timeout=ssh_connect_timeout,
            allow_agent=True,
            look_for_keys=True,
        )

        scp = SCPClient(ssh.get_transport())
        sftp = ssh.open_sftp()
        run_label = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_genome = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in genome)
        remote_job_dir = f"{ssh_rootfolder.rstrip('/')}/tpw_interpro/{safe_genome}_{run_label}"
        remote_input = f"{remote_job_dir}/{genome}.faa.gz"
        remote_output = f"{remote_job_dir}/{genome}.faa.tsv"
        remote_script = f"{remote_job_dir}/run_interproscan.sh"
        remote_slurm = f"{remote_job_dir}/interproscan.slurm"
        remote_stdout = f"{remote_job_dir}/slurm-%j.out"
        remote_stderr = f"{remote_job_dir}/slurm-%j.err"

        mkdir_exit, _, mkdir_err = _run_remote(f"mkdir -p {shlex.quote(remote_job_dir)}")
        if mkdir_exit != 0:
            raise RuntimeError(
                f"Unable to prepare remote InterProScan directory for {genome}: "
                f"{mkdir_err or f'exit status {mkdir_exit}'}"
            )
        scp.put(os.path.join(folder_path, genome + ".faa.gz"), remote_input)

        runner_text = "\n".join([
            "#!/bin/bash",
            "set -euo pipefail",
            'export LD_LIBRARY_PATH="/home/shared/miniconda3.8/envs/interproscan/lib/:$LD_LIBRARY_PATH"',
            'eval "$(/home/shared/miniconda3.8/bin/conda shell.bash hook)"',
            "conda activate interproscan",
            f'JOB_BASE="${{SLURM_TMPDIR:-{remote_job_dir}/slurm_tmp}}"',
            'mkdir -p "$JOB_BASE"',
            f'TMP_ROOT="$(mktemp -d "$JOB_BASE/{safe_genome}_${{SLURM_JOB_ID:-manual}}_XXXXXX")"',
            'trap \'rm -rf "$TMP_ROOT"\' EXIT',
            'mkdir -p "$TMP_ROOT/work" "$TMP_ROOT/out" "$TMP_ROOT/tmp"',
            f'cp {shlex.quote(remote_input)} "$TMP_ROOT/work/{genome}.faa.gz"',
            f'zcat "$TMP_ROOT/work/{genome}.faa.gz" | /grupos/public/iprscan/current/interproscan.sh --pathways --goterms --cpu {ssh_cores} -iprlookup --formats tsv -T "$TMP_ROOT/tmp" -d "$TMP_ROOT/out" -i - -o "$TMP_ROOT/out/{genome}.faa.tsv"',
            f'cp "$TMP_ROOT/out/{genome}.faa.tsv" {shlex.quote(remote_output)}',
            "",
        ])
        slurm_text = "\n".join([
            "#!/bin/bash",
            f"#SBATCH --job-name=ipr_{safe_genome[:20]}",
            f"#SBATCH -p {slurm_partition}",
            f"#SBATCH --cpus-per-task={ssh_cores}",
            f"#SBATCH --time={slurm_time}",
            f"#SBATCH --mem={slurm_mem}",
            f"#SBATCH -o {remote_stdout}",
            f"#SBATCH -e {remote_stderr}",
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
            raise RuntimeError(
                f"Unable to submit remote InterProScan job for {genome}: "
                f"{submit_err or submit_out or f'exit status {submit_exit}'}"
            )
        job_id = submit_out.split(";")[0].strip()
        if not job_id:
            raise RuntimeError(f"Unable to parse Slurm job id for remote InterProScan on {genome}")

        finished = False
        waited_seconds = 0
        last_state = "PENDING"
        while not finished and waited_seconds <= remote_wait_seconds:
            try:
                scp.get(remote_output, folder_path)
                finished = True
            except Exception:
                state_exit, state_out, state_err = _run_remote(
                    f"sacct -j {shlex.quote(job_id)} --format=JobID,State,ExitCode -P -n | head -n 1"
                )
                state_line = state_out.splitlines()[0].strip() if state_out.strip() else ""
                state_parts = state_line.split("|") if state_line else []
                if len(state_parts) >= 3:
                    _, remote_state, remote_exit_code = state_parts[:3]
                    last_state = remote_state or last_state
                    normalized = remote_state.upper()
                    if normalized.startswith(("FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL")):
                        _, slurm_out_text, _ = _run_remote(f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true")
                        _, slurm_err_text, _ = _run_remote(f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true")
                        details = slurm_err_text or slurm_out_text or state_err or "no remote output captured"
                        raise RuntimeError(
                            f"Remote InterProScan failed for {genome} "
                            f"({remote_state} / {remote_exit_code}): {details}"
                        )
                    if normalized.startswith("COMPLETED"):
                        _, slurm_out_text, _ = _run_remote(f"tail -n 120 {shlex.quote(remote_stdout)} 2>/dev/null || true")
                        _, slurm_err_text, _ = _run_remote(f"tail -n 120 {shlex.quote(remote_stderr)} 2>/dev/null || true")
                        details = slurm_err_text or slurm_out_text or "no remote output captured"
                        raise RuntimeError(
                            f"Remote InterProScan finished for {genome} but did not produce "
                            f"{genome}.faa.tsv. Details: {details}"
                        )

                print(
                    f"InterProScan output for {genome} not available yet. "
                    f"Retrying in {remote_poll_seconds} seconds..."
                )
                time.sleep(remote_poll_seconds)
                waited_seconds += remote_poll_seconds

        if not finished:
            raise TimeoutError(
                f"InterProScan output not retrieved for {genome} after "
                f"{waited_seconds} seconds (last remote state: {last_state})"
            )

        with open(tsv_path, "r", encoding="utf-8") as f:
            zipped_content = gzip.compress(bytes(f.read(), "utf-8"))
            with open(tsv_gz_path, "wb") as f2:
                f2.write(zipped_content)
        return 0
    except Exception as exc:
        if not allow_local_fallback:
            raise
        print(f"InterProScan unavailable in local profile ({exc}); using empty InterPro output.")
        with open(tsv_path, "w", encoding="utf-8"):
            pass
        with gzip.open(tsv_gz_path, "wt", encoding="utf-8"):
            pass
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


@bash_app(executors=["local_executor"])
def load_interpro(working_dir, genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    protein_file = os.path.join(folder_path, genome + '.faa.tsv')
    return f"python {working_dir}/manage.py load_interpro {genome} --interpro_tsv {protein_file}"


@bash_app(executors=["local_executor"])
def gbk2uniprot_map(working_dir, genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    unips_lst = os.path.join(folder_path, genome + '_unips.lst')
    unips_not_mapped = os.path.join(
        folder_path, genome + '_unips_not_mapped.lst')
    unips_mapping = os.path.join(folder_path, genome + '_unips_mapping.csv')
    # If we already have a mapping, reuse it to avoid hammering UniProt during local/dev runs
    if _flag_enabled("TPW_REUSE_UNIPROT_MAP", default=False) and os.path.exists(unips_lst) and os.path.getsize(unips_lst) > 0:
        return f"echo 'gbk2uniprot_map: reusing existing {unips_lst}'"
    return f"python {working_dir}/manage.py gbk2uniprot_map {genome} --batch_size 300 --mapping_tmp \
        {unips_mapping} --not_mapped {unips_not_mapped} \
        > {unips_lst}" #Entiendo que queria guardar el stdout


@python_app(executors=["local_executor"])
def get_unipslst(folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
        return unip_lst.read()


@bash_app(executors=["local_executor"])
def alphafold_unips(protein_list, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    alphafold_folder = os.path.join(folder_path, "alphafold")
    accesion, locustag = protein_list.split(' ')[0], protein_list.split(' ')[1]
    return f"python -m TP.alphafold -pr ../opt/p2rank/distro/prank -o \
        {alphafold_folder} -T 10 -nc -parsl {accesion} -ltag {locustag}" #Hay que agregar el locustag en el echo.


@bash_app(executors=["local_executor"])
def load_af_model(locus_tag, working_dir, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    protein_pdb = os.path.join(folder_path, 'alphafold', locus_tag, f"{locus_tag}_af.pdb")
    return f"python {working_dir}/manage.py load_af_model {locus_tag} {protein_pdb} {locus_tag} --overwrite --datadir '../data'"


@python_app(executors=["local_executor"])
def decompress_file(input_file, output_file, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import gzip
    import shutil
    with gzip.open(input_file, 'rb') as f_in:
        with open(output_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)


@python_app(executors=["local_executor"])
def compress_file(input_file, output_file, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import gzip
    import shutil
    with open(input_file, 'r') as f:
        zipped_content = gzip.compress(bytes(f.read(), 'utf-8'))
        with open(output_file, 'wb') as f2:
            f2.write(zipped_content)


@bash_app(executors=["local_executor"])
def run_fpocket(locus_tag, working_dir, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python -m TP.alphafold {locus_tag} -o {folder_path} -w {working_dir} -T 10 -nc -np -na"

@bash_app(executors=["local_executor"])
def fpocket2json(folder_path, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out")
    if os.path.exists(locustag_af):
        return f"python -m SNDG.Structure.FPocket 2json {locustag_af} | gzip > {locustag_af}/fpocket.json.gz"
    else:
        pass

@bash_app(executors=["local_executor"])
def p2rank2json(genome, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py p2rank_2_json {genome} {locus_tag} --datadir '../data'"

@bash_app(executors=["local_executor"])
def load_pocket(folder_path, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out", "fpocket.json.gz")
    return f"python {working_dir}/manage.py load_fpocket --pocket_json {locustag_af} {locus_tag} --datadir '../data'"

@bash_app(executors=["local_executor"])
def load_p2pocket(genome, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore('../data')
    p2pocket_json = ss.p2rank_json(genome, locus_tag)
    return f"python {working_dir}/manage.py load_fpocket --pocket_json {p2pocket_json} {locus_tag} --datadir '../data' --P2rank_pocket"

@python_app(executors=["local_executor"])
def filter_pdb(locus_tag_fold, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    import gzip
    filtered = list()
    with open(f"{locus_tag_fold}/{locus_tag}_af_out/{locus_tag}_af_out.pdb", 'r') as f:
        for line in f.readlines():
            if line[:6] == "HETATM" and "POL" in line and "STP" in line:
                filtered.append(line)
    filtered_str = ('').join(filtered)
    zipped_content = gzip.compress(bytes(filtered_str, 'utf-8'))
    with open(os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), 'ab') as f2:
        f2.write(zipped_content)

@join_app
def strucutures_af(working_dir, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    from Bio import SeqIO
    import pandas as pd
    import os
    protein_ids = pd.read_csv(os.path.join(folder_path, f'{genome}_unips_mapping.csv'), sep=',')
    mapped_proteins = list()
    with open(os.path.join(folder_path, f"{genome}_unips.lst"), 'r') as f:
        mapped_proteins = [x.strip().split()[1] for x in f.readlines()]
    for protein in mapped_proteins:    
        protein_pdb = os.path.join(folder_path, 'alphafold', f'{protein}', f'{protein}_af.pdb')
        print(protein_pdb)
        if os.path.exists(protein_pdb):
            r_load = load_af_model(protein, working_dir,
                                    folder_path,inputs=[mapped_proteins])
            r_json = fpocket2json(
                folder_path, protein, inputs=[r_load])
            p_load = load_pocket(
                folder_path, protein, working_dir, inputs=[r_json])
            r2_json = p2rank2json(genome, protein, working_dir, inputs=[r_load])
            r2_load = load_p2pocket(genome, protein, working_dir, inputs=[r2_json])
            p_load.result()
    return r_load


@bash_app(executors=["local_executor"])
def psort(genome, gram, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python -m TP.psort {genome} -{gram} --tpwebdir /app/targetpathogenweb"

@bash_app(executors=["local_executor"])
def druggability_2_csv(genome, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python {working_dir}/manage.py druggability_2_csv {genome} --datadir ../data"

@bash_app(executors=["local_executor"])
def psort_2_csv(genome, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python {working_dir}/manage.py psort_2_csv {genome} --datadir ../data"

@bash_app(executors=["local_executor"])
def load_score(genome, working_dir, param, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore('../data')
    if param == 'druggability':
        tsv_file = ss.druggability_tsv(genome)
    if param == 'psort':
        tsv_file = ss.psort_tsv(genome)
    if param == 'human_offtarget':
        tsv_file = ss.human_offtarget(genome)
    if param == 'micro_offtarget':
        tsv_file = ss.micro_offtarget(genome)
    if param == 'essenciality':
        tsv_file = ss.essenciality(genome)
    return f"python {working_dir}/manage.py load_score_values {genome}  {tsv_file} --datadir ../data"

@bash_app(executors=["local_executor"])
def fasttarget(genome, working_dir, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python {working_dir}/manage.py fast_command {genome} {folder_path} --datadir ../data"

@bash_app(executors=["local_executor"])
def get_binders(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python {working_dir}/manage.py get_binders {genome} --datadir ../data"

@bash_app(executors=["local_executor"])
def load_binders(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python {working_dir}/manage.py load_binders {genome} --datadir ../data"

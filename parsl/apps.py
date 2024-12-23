import parsl
from parsl import python_app, bash_app, join_app
import time
from parsl.data_provider.files import File
@python_app(executors=['local_executor'])
def clear_folder(folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os, shutil
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)
    return

@bash_app(executors=["local_executor"])
def download_gbk(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python {working_dir}/manage.py download_gbk {genome} --datadir {working_dir}/data"

@bash_app(executors=["local_executor"])
def test_gbk(working_dir, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python {working_dir}/manage.py test --datadir ../data"

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
    return f"python {working_dir}/manage.py index_genome_seq {genome} --datadir {working_dir}/data"


@python_app(executors=['local_executor'])
def interproscan(cfg_dict, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import paramiko
    import os
    import gzip
    from scp import SCPClient
    from config import TargetConfig
    ssh = paramiko.SSHClient()
    ssh_rootfolder = cfg_dict.get("SSH",  "WorkingDir")
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(cfg_dict.get("SSH", "HostName"),
                username=cfg_dict.get(
                    "SSH", "Username", fallback=os.getenv("SSH_USERNAME")),
                password=cfg_dict.get("SSH", "Password", fallback=os.getenv("SSH_PASSWORD")))
    scp = SCPClient(ssh.get_transport())
    scp.put(os.path.join(folder_path, genome + '.faa.gz'), ssh_rootfolder)
    text = ""
    text += f'export LD_LIBRARY_PATH=\\\"/home/shared/miniconda3.8/envs/interproscan/lib/:$LD_LIBRARY_PATH\\\"\n'
    text += f'eval \\\"\$(/home/shared/miniconda3.8/bin/conda shell.bash hook)\\\"\n'
    text += f'conda activate interproscan\n'
    text += f'zcat {genome}.faa.gz | /grupos/public/iprscan/current/interproscan.sh --pathways \
        --goterms --cpu {cfg_dict.get("SSH", "Cores")} -iprlookup --formats tsv -i - -o {ssh_rootfolder}/{genome}.faa.tsv\n'

    stdin, stdout, stderr = ssh.exec_command(
        f'touch script.sh && printf \"{text}\" > script.sh')
    exit_status = stdout.channel.recv_exit_status()

    stdin, stdout, stderr = ssh.exec_command(
        f"srun --nodes=1 --ntasks-per-node=1 --cpus-per-task={cfg_dict.get('SSH', 'Cores')} --time=05:00:00 bash ./script.sh", get_pty=True)
    finished = False
    time_passed = 0
    while not finished and time_passed < 9000:
        try:
            scp.get(f"{ssh_rootfolder}/{genome}.faa.tsv", folder_path)
            finished = True
        except:
            print(f"File '{genome}.faa.tsv' not found. Retrying in 1 minute...")
            time.sleep(60)  # Wait for 1 minute before retrying
            time_passed += 1
    
    scp.close()
    ssh.close()
    with open(os.path.join(folder_path, genome + ".faa.tsv"), 'r') as f:
        zipped_content = gzip.compress(bytes(f.read(), 'utf-8'))
        with open(os.path.join(folder_path, genome + ".faa.tsv.gz"), 'wb') as f2:
            f2.write(zipped_content)
    return exit_status


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
    return f"python {working_dir}/manage.py gbk2uniprot_map {genome} --mapping_tmp \
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





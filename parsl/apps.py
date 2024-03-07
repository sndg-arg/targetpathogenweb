import parsl
from parsl import python_app, bash_app, join_app
import time

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
    while not finished and time_passed < 200: #poner un tope de 3 hs
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
        {alphafold_folder} -T 10 -nc {accesion} -ltag {locustag}" #Hay que agregar el locustag en el echo.


@bash_app(executors=["local_executor"])
def load_af_model(working_dir, folder_path, locus_tag, protein_name, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    locus_tag_fold = os.path.join(folder_path, locus_tag)
    protein_pdb = os.path.join(
        folder_path, 'alphafold/' + protein_name + '/' + protein_name + '_af.pdb')
    return f"python {working_dir}/manage.py load_af_model {locus_tag} {protein_pdb} \
        {locus_tag} --overwrite --datadir {working_dir}/data"


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
def fpocket2json(locus_tag_fold, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(locus_tag_fold, f"{locus_tag}_af_out")
    return f"python -m SNDG.Structure.FPocket 2json {locustag_af} > {locus_tag_fold}/fpocket.json"


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
    protein_ids = pd.read_csv(os.path.join(folder_path, f'{genome}_unips_mapping.csv'),
                              sep=',')
    mapped_proteins = list()
    rets = list()
    with open(os.path.join(folder_path, f"{genome}_unips.lst"), 'r') as f:
        mapped_proteins = [x.strip() for x in f.readlines()]
    input_file = os.path.join(
                        folder_path, genome + ".gbk.gz")
    output_file = os.path.join(
                        folder_path, genome + ".gbk")
    r_descomp0 = decompress_file(input_file, output_file, inputs = inputs)
    r_descomp0.result()
    for record in SeqIO.parse(os.path.join(folder_path, f"{genome}.gbk"), "genbank"):
        for feature in record.features:
            if feature.type == "CDS" and "protein_id" in feature.qualifiers and feature.qualifiers["protein_id"]:
                locus_tag = feature.qualifiers["locus_tag"][0]
                locus_tag_fold = os.path.join(folder_path, locus_tag)
                protein_id = feature.qualifiers["protein_id"][0] #Asume incorrectamente que todo CDS en el genebank posee un protein_ID
                entries = protein_ids.loc[(protein_ids["From"] == protein_id)]["Entry"].unique()
                for e in entries:
                    if e in mapped_proteins:
                        r_load = load_af_model(working_dir,
                                               folder_path, locus_tag, e, inputs=[r_descomp0])
                        input_file = os.path.join(
                            locus_tag_fold, locus_tag + ".pdb.gz")
                        output_file = os.path.join(
                            locus_tag_fold, locus_tag + "_af.pdb")
                        r_descomp = decompress_file(
                            input_file, output_file, inputs=[r_load])
                        r_fpocker = run_fpocket(
                            locus_tag, working_dir, folder_path, inputs=[r_descomp])
                        r_json = fpocket2json(
                            locus_tag_fold, locus_tag, inputs=[r_fpocker])
                        r_comp = compress_file(os.path.join(locus_tag_fold, "fpocket.json"), os.path.join(locus_tag_fold, "fpocket.json.gz"),
                                               inputs=[r_json])
                        r_comp2 = compress_file(os.path.join(locus_tag_fold, "fpocket.json"), os.path.join(
                            locus_tag_fold, locus_tag + ".pdb.gz"), inputs=[r_comp])
                        rets.append(filter_pdb(locus_tag_fold,
                                    locus_tag, inputs=[r_comp2]))
    return rets

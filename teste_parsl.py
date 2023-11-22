import parsl
from parsl import python_app, bash_app, join_app
import math
import os
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider, SlurmProvider
from parsl.channels import LocalChannel, SSHChannel
from parsl.launchers import SrunLauncher
from parsl.addresses import address_by_hostname, address_by_query
from parsl.monitoring.monitoring import MonitoringHub


@bash_app(executors=["local_executor"])
def download_gbk(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python manage.py download_gbk {genome}"


@bash_app(executors=["local_executor"])
def load_gbk(gbk_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python manage.py load_gbk {gbk_path} --overwrite --accession {genome}"


@bash_app(executors=["local_executor"])
def index_genome_db(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python manage.py index_genome_db {genome}"


@bash_app(executors=["local_executor"])
def index_genome_seq(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python manage.py index_genome_seq {genome}"

# @bash_app(executors=["slurm_executor"])
# def interproscan(genome, inputs = [], stderr = parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
#     zcat = f'zcat /home/rterra/{genome}'
#     app_dir = "/grupos/public/iprscan/current/interproscan.sh"
#     parameters = f"--pathways --goterms --cpu 8 -iprlookup --formats tsv -i - -o {genome.split('.')[0]}.faa.tsv"
#     return f"cd /home/rterra/;{zcat} | {app_dir} {parameters}"

# need testing
@bash_app(executors=["slurm_executor"])
def interproscan(folder_path, genome, inputs = [], stderr = parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
    ssh_rootfolder = HighThroughputExecutor.run_dir
    with open(os.path.join(folder_path, "script.sh"), 'w') as sc:
        text = ""
        text += f'export LD_LIBRARY_PATH=\\\"/home/shared/miniconda3.8/envs/interproscan/lib/:$LD_LIBRARY_PATH\\\"\n'
        text += f'eval \\\"\$(/home/rterra/miniconda3/bin/conda shell.bash hook)\\\"\n'
        text += f'conda activate interproscan_custom\n'
        text += f'zcat {genome}.faa.gz | /grupos/public/iprscan/current/interproscan.sh --pathways \
            --goterms --cpu 10 -iprlookup --formats tsv -i - -o {ssh_rootfolder}/{genome.split(".")[0]}.faa.tsv\n'
    SSHChannel.push_file(os.path.join(folder_path, "script.sh"), ssh_rootfolder)
    
    return f"srun --nodes=1 --ntasks-per-node=1 --cpus-per-task=10 --time=05:00:00 bash ./script.sh"

@python_app(executors=["slurm_executor"])
def get_interpro_result(folder_path, genome, inputs = [], stderr = parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
    ssh_rootfolder = HighThroughputExecutor.run_dir
    SSHChannel.pull_file(os.path.join(ssh_rootfolder, genome + ".faa.tsv"), folder_path)
    return

@bash_app(executors=["local_executor"])
def load_interpro(genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    protein_file = os.path.join(folder_path, genome + '.faa.tsv')
    return f"python manage.py load_interpro {genome} --interpro_tsv {protein_file}"


@bash_app(executors=["local_executor"])
def gbk2uniprot_map(genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    unips_lst = os.path.join(folder_path, genome + '_unips.lst')
    unips_not_mapped = os.path.join(
        folder_path, genome + '_unips_not_mapped.lst')
    unips_mapping = os.path.join(folder_path, genome + '_unips_mapping.csv')
    return f"python manage.py gbk2uniprot_map {genome} --mapping_tmp \
        {unips_mapping} --not_mapped {unips_not_mapped} \
        > {unips_lst}"


@python_app(executors=["local_executor"])
def get_unipslst(folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
        return unip_lst.readlines()


@bash_app(executors=["local_executor"])
def alphafold_unips(protein_list, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    alphafold_folder = os.path.join(folder_path, "alphafold")
    return f"echo \"{protein_list}\" | python -m TP.alphafold -pr /opt/p2rank_2.4/prank -o \
        {alphafold_folder} -T 1 -nc"


@bash_app(executors=["local_executor"])
def load_af_model(folder_path, locus_tag, protein_name, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    locus_tag_fold = os.path.join(folder_path, locus_tag)
    protein_pdb = os.path.join(
        folder_path, 'alphafold/' + protein_name + '/' + protein_name + '_AF.pdb')
    return f"python manage.py load_af_model {locus_tag} {protein_pdb} \
        {locus_tag} --overwrite"


@python_app(executors=["local_executor"])
def descompress_file(input_file, output_file, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
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
def run_fpocket(locus_tag, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python -m TP.alphafold {locus_tag} -o {folder_path} -T 10 -nc -np -na"


@bash_app(executors=["local_executor"])
def fpocket2json(locus_tag_fold, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(locus_tag_fold, f"{locus_tag}_AF_out")
    return f"python -m SNDG.Structure.FPocket 2json {locustag_af} > fpocket.json"


@python_app(executors=["local_executor"])
def filter_pdb(locus_tag_fold, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    import gzip
    filtered = list()
    with open(f"{locus_tag_fold}/{locus_tag}_AF_out/{locus_tag}_AF_out.pdb", 'r') as f:
        for line in f.readlines():
            if line[:6] == "HETATM" and "POL" in line and "STP" in line:
                filtered.append(line)
    filtered_str = ('').join(filtered)
    zipped_content = gzip.compress(bytes(filtered_str, 'utf-8'))
    with open(os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), 'ab') as f2:
        f2.write(zipped_content)


@join_app
def strucutures_af(folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    from Bio import SeqIO
    import pandas as pd
    import os
    protein_ids = pd.read_csv(os.path.join(folder_path, f'{genome}_unips_mapping.csv'),
                              sep=',')
    mapped_proteins = list()
    rets = list()
    with open(os.path.join(folder_path, f"{genome}_unips.lst"), 'r') as f:
        mapped_proteins = [x.strip() for x in f.readlines()]
    for record in SeqIO.parse(os.path.join(folder_path, f"{genome}.gbk"), "genbank"):
        for feature in record.features:
            if feature.type == "CDS":
                locus_tag = feature.qualifiers["locus_tag"][0]
                locus_tag_fold = os.path.join(folder_path, locus_tag)
                protein_id = feature.qualifiers["protein_id"][0]
                entries = protein_ids.loc[(
                    protein_ids["From"] == protein_id)]["Entry"].unique()
                for e in entries:
                    if e in mapped_proteins:
                        r_load = load_af_model(
                            folder_path, locus_tag, e, inputs=inputs)
                        input_file = os.path.join(
                            locus_tag_fold, locus_tag + ".pdb.gz")
                        output_file = s.path.join(
                            locus_tag_fold, locus_tag + "_AF.pdb")
                        r_descomp = descompress_file(
                            input_file, output_file, inputs=[r_load])
                        r_fpocker = run_fpocket(
                            locus_tag, folder_path, inputs=[r_descomp])
                        r_json = fpocket2json(
                            locus_tag_fold, locus_tag, inputs=[r_fpocker])
                        r_comp = compress_file(os.path.join(locus_tag_fold, "fpocket.json"), os.path.join(locus_tag_fold, "fpocket.json.gz"),
                                               inputs=[r_json])
                        r_comp2 = compress_file(os.path.join(locus_tag_fold, "fpocket.json"), os.path.join(
                            locus_tag_fold, locus_tag + ".pdb.gz"), inputs=[r_comp])
                        rets.append(filter_pdb(locus_tag_fold,
                                    locus_tag, inputs=[r_comp2]))
    return rets


# ---------------------------
ht_executor = HighThroughputExecutor(
    working_dir=os.getcwd(),
    label="local_executor",
    provider=LocalProvider(channel=LocalChannel(),
                           min_blocks=1,
                           max_blocks=1,
                           parallelism=0,
                           nodes_per_block=1,
                           worker_init="export DJANGO_DEBUG=True;export DJANGO_SETTINGS_MODULE=tpwebconfig.settings;\
                export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp;\
                export CELERY_BROKER_URL=redis://localhost:6379/0;\
                export PYTHONPATH=$PYTHONPATH:../sndgjobs:../sndgbiodb:../targetpathogen:../sndg-bio;\
                conda activate tpv2"),
    max_workers=4,

)

slurm_executor = HighThroughputExecutor(
    label="slurm_executor",
    working_dir = "/home/rterra/",
    worker_logdir_root="/home/rterra",
    provider = LocalProvider(channel=SSHChannel(
        username=os.getenv('SSH_USERNAME'),
        password=os.getenv('SSH_PASSWORD'),
        hostname='cluster.qb.fcen.uba.ar',
        script_dir='/home/rterra/slurm_target_tests'
    )
)
)
cfg = Config(monitoring=MonitoringHub(
    hub_address=address_by_hostname(),
    monitoring_debug=False,
    resource_monitoring_interval=10,
    ),
    executors=[ht_executor, slurm_executor]
)



parsl.load(cfg)
# ----------------------------------------


@join_app
def run(genome):
    genome = genome.split('.')[0]
    import math
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = f"./data/{folder_name}/{genome}"
    r_interpro = interproscan(genome, inputs=[])
    r_interpror = get_interpro_result(folder_path=folder_path, genome = genome, inputs=[r_interpro])
    """
    r_down = download_gbk(genome=genome)
    r_load = load_gbk(gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz"),genome=genome, inputs=[r_down])
    r_index_db = index_genome_db(inputs=[r_load], genome=genome)
    r_index_seq = index_genome_seq(inputs=[r_index_db], genome=genome)
    r_interpro = interproscan(genome, inputs=[r_index_seq])
    r_load_interpro = load_interpro(genome, folder_path, inputs=[r_interpro])
    r_gbk2uniprot = gbk2uniprot_map(genome, folder_path, inputs = [r_load_interpro])
    protein_list = get_unipslst(folder_path, genome, inputs=[r_gbk2uniprot])
    r_alphafolds = list()
    for proteins in (protein_list.result()).split('\n'):
        r = alphafold_unips(proteins, folder_path,
                            genome, inputs=[protein_list])
        r_alphafolds.append(r)
    # -----------------------------------
    r_stru = strucutures_af(folder_path, genome, inputs=r_alphafolds)

    """
    for r in [r_interpror]:
        r.result()


if __name__ == "__main__":
    parsl.set_stream_logger()
    run(genome="NC_003047")

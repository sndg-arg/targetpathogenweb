import parsl
from parsl import python_app, bash_app, join_app
import math
import os
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
from parsl.channels import LocalChannel
from parsl.addresses import address_by_hostname
from parsl.monitoring.monitoring import MonitoringHub


@bash_app
def download_gbk(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    return f"python manage.py download_gbk {genome}"

@bash_app
def load_gbk(gbk_path, genome, inputs = [], stderr = parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
    return f"python manage.py load_gbk {gbk_path} --overwrite --accession {genome}"

@bash_app
def index_genome_db(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python manage.py index_genome_db {genome}"


@bash_app
def index_genome_seq(genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python manage.py index_genome_seq {genome}"


@bash_app
def load_interpro(genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    protein_file = os.path.join(folder_path, genome + '.faa.tsv')
    return f"python manage.py load_interpro {genome} --interpro_tsv {protein_file}"


@bash_app
def gbk2uniprot_map(genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    unips_lst = os.path.join(folder_path, genome + '_unips.lst')
    unips_not_mapped = os.path.join(
        folder_path, genome + '_unips_not_mapped.lst')
    unips_mapping = os.path.join(folder_path, genome + '_unips_mapping.csv')
    return f"python manage.py gbk2uniprot_map {genome} --mapping_tmp \
        {unips_mapping} --not_mapped {unips_not_mapped} \
        > {unips_lst}"


@python_app
def get_unipslst(folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
    with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
        return unip_lst.read()

@bash_app
def alphafold_unips(protein_list, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    alphafold_folder = os.path.join(folder_path, "alphafold")
    return f"echo \"{protein_list}\" | python -m TP.alphafold -pr /opt/p2rank_2.4/prank -o \
        {alphafold_folder} -T 1 -nc"



@bash_app
def load_af_model(folder_path, locus_tag, protein_name, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    locus_tag_fold = os.path.join(folder_path, locus_tag)
    protein_pdb = os.path.join(
        folder_path, 'alphafold/' + protein_name + '/' + protein_name + '_AF.pdb')
    return f"python manage.py load_af_model {locus_tag} {protein_pdb} \
        {locus_tag} --overwrite"


@python_app
def descompress_file(input_file, output_file, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import gzip
    import shutil
    with gzip.open(input_file, 'rb') as f_in:
        with open(output_file, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

@python_app
def compress_file(input_file, output_file, inputs = [], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import gzip
    import shutil
    with open(input_file, 'r') as f:
        zipped_content = gzip.compress(bytes(f.read(), 'utf-8'))
        with open(output_file, 'wb') as f2:
            f2.write(zipped_content)

@bash_app
def run_fpocket(locus_tag, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python -m TP.alphafold {locus_tag} -o {folder_path} -T 10 -nc -np -na"


@bash_app
def fpocket2json(locus_tag_fold, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(locus_tag_fold, f"{locus_tag}_AF_out")
    return f"python -m SNDG.Structure.FPocket 2json locustag_af > fpocket.json"


parsl.load(Config(monitoring=MonitoringHub(
    hub_address=address_by_hostname(),
    monitoring_debug=False,
    resource_monitoring_interval=10,
),
    executors=[HighThroughputExecutor(
        working_dir = os.getcwd(),
        provider=LocalProvider(channel=LocalChannel(),
                               worker_init="export JANGO_DEBUG=True;export DJANGO_SETTINGS_MODULE=tpwebconfig.settings;\
                    export DJANGO_DATABASE_URL=psql://postgres:123@127.0.0.1:5432/tp;\
                    export CELERY_BROKER_URL=redis://localhost:6379/0;\
                    export PYTHONPATH=$PYTHONPATH:../sndgjobs:../sndgbiodb:../targetpathogen:../sndg-bio;\
                    conda activate tpv2"),
        label="executor-01",
        max_workers=4,


    )

]
))
@python_app
def filter_pdb(locus_tag_fold, locus_tag, inputs = [], stderr = parsl.AUTO_LOGNAME, stdout = parsl.AUTO_LOGNAME):
    import os, gzip
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
def strucutures_af(folder_path, genome, inputs = [], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    from Bio import SeqIO
    import pandas as pd
    import os
    protein_ids = pd.read_csv(os.path.join(folder_path, f'{genome}_unips_mapping.csv'),
            sep = ',')
    mapped_proteins = list()
    with open(os.path.join(folder_path, f"{genome}_unips.lst"), 'r') as f:
        mapped_proteins = [x.strip() for x in f.readlines()]
    for record in SeqIO.parse(os.path.join(folder_path, f"{genome}.gbk"), "genbank"):
        for feature in record.features:
            if feature.type == "CDS":
                locus_tag = feature.qualifiers["locus_tag"][0]
                locus_tag_fold = os.path.join(folder_path, locus_tag)
                protein_id = feature.qualifiers["protein_id"][0]
                entries = protein_ids.loc[(protein_ids["From"] == protein_id)]["Entry"].unique()
                for e in entries:
                    if e in mapped_proteins:
                        r_load = load_af_model(folder_path, locus_tag, e, inputs=inputs)
                        input_file = os.path.join(locus_tag_fold, locus_tag + ".pdb.gz")
                        output_file = s.path.join(locus_tag_fold, locus_tag + "_AF.pdb")
                        r_descomp = descompress_file(input_file, output_file, inputs=[r_load])
                        r_fpocker = run_fpocket(locus_tag, folder_path, inputs=[r_descomp])
                        r_json = fpocket2json(locus_tag_fold, locus_tag)
                        r_comp = compress_file(os.path.join(locus_tag_fold, "fpocket.json"), os.path.join(locus_tag_fold, "fpocket.json.gz"),
                                               inputs=[r_json])
                        r_comp2 = compress_file(os.path.join(locus_tag_fold, "fpocket.json"),os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), inputs = [r_comp])
                        filter_pdb(locus_tag_fold, locus_tag, inputs=[r_comp2])




@join_app
def run(genome):
    import math
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = f"./data/{folder_name}/{genome}"
    """
    r_down = download_gbk(genome=genome)
    r_load = load_gbk(gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz"),genome=genome, inputs=[r_down])
    r_index_db = index_genome_db(inputs=[r_load], genome=genome)
    r_index_seq = index_genome_seq(inputs=[r_index_db], genome=genome)
    #interproscan
    r_load_interpro = load_interpro(genome, folder_path, inputs=[r_index_seq])
    r_gbk2uniprot = gbk2uniprot_map(genome, folder_path, inputs = [r_load_interpro)
    protein_list = get_unipslst(folder_path, genome, inputs = [r_gbk2uniprot])
    """
    protein_list = get_unipslst(folder_path, genome, inputs = [])
    r_alphafolds = list()
    for proteins in (protein_list.result()).split('\n'):
        r = alphafold_unips(proteins, folder_path, genome, inputs = [protein_list])
        r_alphafolds.append(r)
    #-----------------------------------
    strucutures_af(folder_path, genome, inputs=r_alphafolds)
if __name__ == "__main__":
    parsl.set_stream_logger()
    run(genome = "AE009440")
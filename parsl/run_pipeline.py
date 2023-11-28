import parsl
from parsl import join_app
from config import *
from apps import *

@join_app
def run(genome):
    genome = genome.split('.')[0]
    import math, os
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = f"./data/{folder_name}/{genome}"
    r_interpro = interproscan(genome, inputs=[] )
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
    cfg = TargetConfig("settings.ini")
    parsl.load(cfg.get_parsl_cfg())
    parsl.set_stream_logger()
    run(genome="NC_003047")

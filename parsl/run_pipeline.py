import parsl
from parsl import join_app
from config import *
from apps import *
import argparse
import sys

@join_app
def run(genome):
    import math
    import os

    genome = genome.split('.')[0]
    cfg = TargetConfig()
    cfg_dict = cfg.get_config_dict()
    # store the necessary paths
    working_dir = cfg_dict.get("GENERAL", "WorkingDir")
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = os.path.join(working_dir, f"data/{folder_name}/{genome}")

    # starts the pipeline

    # requires working dir to save data
    r_down = download_gbk(working_dir=working_dir, genome=genome)
    r_load = load_gbk(working_dir=working_dir,
                      folder_path=folder_path, genome=genome, inputs=[r_down])
    r_index_db = index_genome_db(working_dir=working_dir, inputs=[
                                 r_load], genome=genome)
    r_index_seq = index_genome_seq(working_dir=working_dir, inputs=[
                                   r_index_db], genome=genome)
    r_interpro = interproscan(cfg_dict=cfg_dict, folder_path=folder_path, genome=genome, inputs=[r_index_seq])
    r_load_interpro = load_interpro(
        working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_interpro])
    r_gbk2uniprot = gbk2uniprot_map(
        working_dir=working_dir, genome=genome, folder_path=folder_path, inputs=[r_load_interpro])
    protein_list = get_unipslst(
        folder_path=folder_path, genome=genome, inputs=[r_gbk2uniprot])
    r_alphafolds = list()
    for proteins in (protein_list.result()).split('\n'):
        if len(proteins) > 0:
            r = alphafold_unips(protein_list=proteins, folder_path=folder_path,
                            genome=genome, inputs=[protein_list])
            r_alphafolds.append(r)
    # -----------------------------------
    r_stru = strucutures_af(
        working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=r_alphafolds)
    return r_stru


if __name__ == "__main__":
    genomes = list()
    parser = argparse.ArgumentParser()
    parser.add_argument('genomes', help="List of NCBI genomes accession numbers separated with new lines",
                        type=str,
                        nargs='*',
                        default=sys.stdin)
    args = parser.parse_args()
    for l in args.genomes:
        genomes.append(l.strip().upper())
    cfg = TargetConfig("settings.ini")
    parsl.load(cfg.get_parsl_cfg())
    parsl.set_stream_logger()
    results = list()
    for genome in genomes:
        r = run(genome=genome)
        results.append(r)
    for r in results:
        r.result()

import parsl
from parsl import join_app
from config import *
from apps import *
import argparse
import sys

@join_app
def run(genome, gram, custom):
    import math
    import os

    #genome = genome.split('.')[0]
    
    cfg = TargetConfig()
    cfg_dict = cfg.get_config_dict()
    # store the necessary paths
    working_dir = cfg_dict.get("GENERAL", "WorkingDir")
    acclen = len(genome)
    folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
    folder_path = os.path.join(working_dir, f"data/{folder_name}/{genome}")

    # starts the pipeline

    # requires working dir to save data
    r_clear = clear_folder(folder_path=folder_path, inputs = [])
    
    if args.test:
        r_down = test_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear])
    elif args.custom:
        r_down = custom_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear], custom=custom)
    else:
        r_down = download_gbk(working_dir=working_dir, genome=genome, inputs=[r_clear])
    r_load = load_gbk(working_dir=working_dir,
                      folder_path=folder_path, genome=genome, inputs=[r_down])
    r_fasttarget = fasttarget(working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=[r_load])
    load_human_offt = load_score(working_dir=working_dir, genome=genome, inputs=[r_fasttarget], param = 'human_offtarget')
    load_micro_offt = load_score(working_dir=working_dir, genome=genome, inputs=[load_human_offt], param = 'micro_offtarget')
    load_essen = load_score(working_dir=working_dir, genome=genome, inputs=[load_micro_offt], param = 'essenciality')
    r_index_db = index_genome_db(working_dir=working_dir, inputs=[
                                 load_essen], genome=genome)
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
    
    r_stru = strucutures_af(
        working_dir=working_dir, folder_path=folder_path, genome=genome, inputs=r_alphafolds)
    
    d_2_csv = druggability_2_csv(working_dir=working_dir, genome=genome, inputs =[r_stru])

    load_d = load_score(working_dir=working_dir, genome=genome, inputs=[d_2_csv], param = 'druggability')
    
    p_run = psort(genome= genome, gram= gram, inputs=[r_stru])

    load_p = load_score(working_dir=working_dir, genome=genome, inputs=[p_run], param = 'psort')

    return load_p

if __name__ == "__main__":
    genomes = list()
    parser = argparse.ArgumentParser()
    parser.add_argument('genomes', help="List of NCBI genomes accession numbers separated with new lines",
                        type=str,
                        nargs='*',
                        default=sys.stdin)
    parser.add_argument('--test', '-t', action='store_true', help="Run in test mode")
    parser.add_argument('--gram', choices=['p', 'n'], default=None, help="Specify 'p' for Gram-positive or 'n' for Gram-negative bacteria, optional")
    parser.add_argument('--custom','-c', default=None, help="Specify the path to the custom GBK file")

    args = parser.parse_args()
    gram = args.gram
    custom = args.custom
    if args.test:
        genomes=['NZ_AP023069.1']
        gram = 'n'
    elif args.custom:
        path, file = os.path.split(custom)
        ncbi_code = file.split(".g")[0]
        genomes=[ncbi_code]
    else:
        for l in args.genomes:
            genomes.append(l.strip().upper())
    cfg = TargetConfig("settings.ini")
    parsl.load(cfg.get_parsl_cfg())
    parsl.set_stream_logger()
    results = list()

    for genome in genomes:
        r = run(genome=genome, gram=gram, custom=custom)
        results.append(r)
    for r in results:
        r.result()

import parsl
from parsl import python_app, bash_app, join_app
import os
from parsl.data_provider.files import File
from interproscan_remote import run_remote_interproscan


def _flag_enabled(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

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


@python_app(executors=['local_executor'])
def interproscan(cfg_dict, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return run_remote_interproscan(cfg_dict=cfg_dict, folder_path=folder_path, genome=genome)


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


@bash_app(executors=["local_executor"])
def fetch_uniprot_annotations(working_dir, genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    lst_path = os.path.join(folder_path, genome + '_unips.lst')
    return f"python {working_dir}/manage.py fetch_uniprot_annotations {genome} --datadir {working_dir}/data --lst {lst_path}"


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
def esmfold_predict(working_dir, genome, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py esmfold_predict {genome} --datadir {working_dir}/data"


@bash_app(executors=["local_executor"])
def load_af_model(locus_tag, working_dir, folder_path, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    import os
    protein_pdb = os.path.join(folder_path, 'alphafold', locus_tag, f"{locus_tag}_af.pdb")
    return f"python {working_dir}/manage.py load_af_model {locus_tag} {protein_pdb} {locus_tag} --overwrite --datadir '../data'"


@bash_app(executors=["local_executor"])
def fpocket2json(folder_path, locus_tag, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out")
    if os.path.exists(locustag_af):
        return f"python -m SNDG.Structure.FPocket 2json {locustag_af} | gzip > {locustag_af}/fpocket.json.gz"
    return f"echo 'No fpocket output for {locus_tag}, skipping'"

@bash_app(executors=["local_executor"])
def p2rank2json(genome, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return f"python {working_dir}/manage.py p2rank_2_json {genome} {locus_tag} --datadir '../data'"

@bash_app(executors=["local_executor"])
def load_pocket(folder_path, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out", "fpocket.json.gz")
    if os.path.exists(locustag_af):
        return f"python {working_dir}/manage.py load_fpocket --pocket_json {locustag_af} {locus_tag} --datadir '../data'"
    return f"echo 'No fpocket data for {locus_tag}, skipping'"

@bash_app(executors=["local_executor"])
def load_p2pocket(genome, locus_tag, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore('../data')
    p2pocket_json = ss.p2rank_json(genome, locus_tag)
    return f"python {working_dir}/manage.py load_fpocket --pocket_json {p2pocket_json} {locus_tag} --datadir '../data' --P2rank_pocket"

@join_app
def structures_af(working_dir, folder_path, genome, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    import os

    alphafold_dir = os.path.join(folder_path, 'alphafold')

    # Scan all locus tags that have a PDB file (from AlphaFold DB or ESMFold)
    proteins_with_pdb = []
    if os.path.isdir(alphafold_dir):
        for locus_tag in sorted(os.listdir(alphafold_dir)):
            pdb_path = os.path.join(alphafold_dir, locus_tag, f'{locus_tag}_af.pdb')
            if os.path.exists(pdb_path) and os.path.getsize(pdb_path) > 0:
                proteins_with_pdb.append(locus_tag)

    if not proteins_with_pdb:
        print("No protein structures found to load.")
        return None

    print(f"Loading {len(proteins_with_pdb)} structures...")
    all_terminal_futures = []
    for protein in proteins_with_pdb:
        print(os.path.join(alphafold_dir, protein, f'{protein}_af.pdb'))
        r_load = load_af_model(protein, working_dir,
                                folder_path, inputs=[proteins_with_pdb])
        r_json = fpocket2json(
            folder_path, protein, inputs=[r_load])
        p_load = load_pocket(
            folder_path, protein, working_dir, inputs=[r_json])
        r2_json = p2rank2json(genome, protein, working_dir, inputs=[r_load])
        r2_load = load_p2pocket(genome, protein, working_dir, inputs=[r2_json])
        all_terminal_futures.append(p_load)
        all_terminal_futures.append(r2_load)
    return all_terminal_futures


@bash_app(executors=["local_executor"])
def psort(genome, gram, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME):
    return (
        "if command -v docker >/dev/null 2>&1; then "
        f"python -m TP.psort {genome} -{gram} --tpwebdir /app/targetpathogenweb "
        f"|| python /app/targetpathogenweb/manage.py tpweb_psort_fallback {genome} --datadir ../data; "
        "else "
        f"python /app/targetpathogenweb/manage.py tpweb_psort_fallback {genome} --datadir ../data; "
        "fi"
    )

@bash_app(executors=["local_executor"])
def druggability_2_csv(genome, working_dir, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    return f"python {working_dir}/manage.py druggability_2_csv {genome} --datadir ../data"

@bash_app(executors=["local_executor"])
def load_score(genome, working_dir, param, inputs=[], stderr=parsl.AUTO_LOGNAME, stdout=parsl.AUTO_LOGNAME, **kwargs):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore('../data')
    tsv_getters = {
        'druggability': ss.druggability_tsv,
        'psort': ss.psort_tsv,
        'human_offtarget': ss.human_offtarget,
        'micro_offtarget': ss.micro_offtarget,
        'essenciality': ss.essenciality,
    }
    getter = tsv_getters.get(param)
    if getter is None:
        raise ValueError(f"Unknown score param: {param}")
    tsv_file = getter(genome)
    return f"python {working_dir}/manage.py load_score_values {genome} {tsv_file} --datadir ../data"

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

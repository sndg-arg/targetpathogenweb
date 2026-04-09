"""
Pure command builders for each pipeline stage.

Each function returns a bash command string — no Parsl dependency.
Extracted from apps.py @bash_app definitions.
"""
import os
import shlex
import sys


PYTHON_BIN = shlex.quote(sys.executable)


# --- Stage 2: Genome download variants ---

def download_gbk_cmd(working_dir, genome, target_accession=None):
    cmd = f"{PYTHON_BIN} {working_dir}/manage.py tpweb_download_gbk {genome} --datadir {working_dir}/data"
    if target_accession:
        cmd += f" --target-accession {target_accession}"
    return cmd


def test_gbk_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py tpweb_test_gbk --datadir ../data --target-accession {genome}"


def custom_gbk_cmd(working_dir, genome, custom):
    return f"{PYTHON_BIN} {working_dir}/manage.py custom_gbk {genome} --datadir ../data --custom {custom}"


# --- Stage 3: Load genome ---

def load_gbk_cmd(working_dir, folder_path, genome):
    gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz")
    return f"{PYTHON_BIN} {working_dir}/manage.py load_gbk {gbk_path} --overwrite --accession {genome} --datadir {working_dir}/data"


# --- Stage 4: FastTarget ---

def fasttarget_cmd(working_dir, genome, folder_path):
    return f"{PYTHON_BIN} {working_dir}/manage.py fast_command {genome} {folder_path} --datadir ../data"


# --- Stages 5-7, 19, 21: Score loading ---

def load_score_cmd(working_dir, genome, param):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore("../data")
    tsv_getters = {
        "druggability": ss.druggability_tsv,
        "psort": ss.psort_tsv,
        "human_offtarget": ss.human_offtarget,
        "micro_offtarget": ss.micro_offtarget,
        "essenciality": ss.essenciality,
    }
    getter = tsv_getters.get(param)
    if getter is None:
        raise ValueError(f"Unknown score param: {param}")
    tsv_file = getter(genome)
    return f"{PYTHON_BIN} {working_dir}/manage.py load_score_values {genome} {tsv_file} --datadir ../data"


# --- Stage 8-9: Indexing ---

def index_db_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py index_genome_db {genome} --datadir {working_dir}/data"


def index_seq_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py index_genome_seq_clean {genome} --datadir {working_dir}/data"


# --- Stage 11: Load InterPro ---

def load_interpro_cmd(working_dir, genome, folder_path):
    protein_file = os.path.join(folder_path, genome + ".faa.tsv")
    return f"{PYTHON_BIN} {working_dir}/manage.py load_interpro {genome} --interpro_tsv {protein_file}"


# --- Stage 12: UniProt mapping ---

def gbk2uniprot_cmd(working_dir, genome, folder_path):
    unips_lst = os.path.join(folder_path, genome + "_unips.lst")
    unips_not_mapped = os.path.join(folder_path, genome + "_unips_not_mapped.lst")
    unips_mapping = os.path.join(folder_path, genome + "_unips_mapping.csv")
    return (
        f"{PYTHON_BIN} {working_dir}/manage.py gbk2uniprot_map {genome} --batch_size 300"
        f" --mapping_tmp {unips_mapping} --not_mapped {unips_not_mapped}"
        f" > {unips_lst}"
    )


# --- Stage 13: Fetch UniProt annotations ---

def fetch_annotations_cmd(working_dir, genome, folder_path):
    lst_path = os.path.join(folder_path, genome + "_unips.lst")
    return f"{PYTHON_BIN} {working_dir}/manage.py fetch_uniprot_annotations {genome} --datadir {working_dir}/data --lst {lst_path}"


# --- Stage 15: AlphaFold per-protein ---

def alphafold_cmd(protein_list_line, folder_path, genome):
    alphafold_folder = os.path.join(folder_path, "alphafold")
    parts = protein_list_line.split()
    accession, locustag = parts[0], parts[1]
    return (
        f"{PYTHON_BIN} -m TP.alphafold -pr ../opt/p2rank/distro/prank"
        f" -o {alphafold_folder} -T 10 -nc -parsl {accession} -ltag {locustag}"
    )


# --- Stage 16: ESMFold ---

def esmfold_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py esmfold_predict {genome} --datadir {working_dir}/data"


# --- Stage 17: Structure loading sub-stages ---

def load_af_model_cmd(locus_tag, working_dir, folder_path):
    protein_pdb = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af.pdb")
    return f"{PYTHON_BIN} {working_dir}/manage.py load_af_model {locus_tag} {protein_pdb} {locus_tag} --overwrite --datadir '../data'"


def fpocket2json_cmd(folder_path, locus_tag):
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out")
    if os.path.exists(locustag_af):
        return f"{PYTHON_BIN} -m SNDG.Structure.FPocket 2json {locustag_af} | gzip > {locustag_af}/fpocket.json.gz"
    return f"echo 'No fpocket output for {locus_tag}, skipping'"


def load_pocket_cmd(folder_path, locus_tag, working_dir):
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out", "fpocket.json.gz")
    if os.path.exists(locustag_af):
        return f"{PYTHON_BIN} {working_dir}/manage.py load_fpocket --pocket_json {locustag_af} {locus_tag} --datadir '../data'"
    return f"echo 'No fpocket data for {locus_tag}, skipping'"


def p2rank2json_cmd(genome, locus_tag, working_dir):
    return f"{PYTHON_BIN} {working_dir}/manage.py p2rank_2_json {genome} {locus_tag} --datadir '../data'"


def load_p2pocket_cmd(genome, locus_tag, working_dir):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore("../data")
    p2pocket_json = ss.p2rank_json(genome, locus_tag)
    return f"{PYTHON_BIN} {working_dir}/manage.py load_fpocket --pocket_json {p2pocket_json} {locus_tag} --datadir '../data' --P2rank_pocket"


# --- Stage 18: Druggability ---

def druggability_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py druggability_2_csv {genome} --datadir ../data"


# --- Stage 20: PSORT ---

def psort_cmd(genome, gram):
    fallback = f"{PYTHON_BIN} /app/targetpathogenweb/manage.py tpweb_psort_fallback {genome} --datadir ../data"
    return (
        f"if command -v docker >/dev/null 2>&1; then "
        f"{PYTHON_BIN} -m TP.psort {genome} -{gram} --tpwebdir /app/targetpathogenweb "
        f"|| {fallback}; "
        f"else {fallback}; fi"
    )


# --- Stages 22-23: Binders ---

def get_binders_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py get_binders {genome} --datadir ../data"


def load_binders_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py load_binders {genome} --datadir ../data"

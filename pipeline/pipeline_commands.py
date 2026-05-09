"""
Pure command builders for each pipeline stage.

Each function returns a bash command string — no Parsl dependency.
Extracted from apps.py @bash_app definitions.
"""
import os
import shlex
import sys


PYTHON_BIN = shlex.quote(sys.executable)


def _data_dir(working_dir):
    return os.path.join(working_dir, "data")


def _host_bind_path(container_path, env_name, container_base):
    host_base = os.environ.get(env_name, "").strip()
    container_base = os.path.abspath(container_base)
    container_path = os.path.abspath(container_path)
    if not host_base or not (
        container_path == container_base
        or container_path.startswith(container_base + os.sep)
    ):
        return container_path
    if not os.path.isabs(host_base):
        cwd = os.environ.get("CWD", "").strip()
        if cwd:
            host_base = os.path.abspath(os.path.join(cwd, host_base))
    rel_path = os.path.relpath(container_path, container_base)
    return host_base if rel_path == "." else os.path.join(host_base, rel_path)


# --- Stage 2: Genome download variants ---

def download_gbk_cmd(working_dir, genome, target_accession=None):
    cmd = f"{PYTHON_BIN} {working_dir}/manage.py tpweb_download_gbk {genome} --datadir {working_dir}/data"
    if target_accession:
        cmd += f" --target-accession {target_accession}"
    return cmd


def test_gbk_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py tpweb_test_gbk --datadir {_data_dir(working_dir)} --target-accession {genome}"


def custom_gbk_cmd(working_dir, genome, custom):
    return f"{PYTHON_BIN} {working_dir}/manage.py custom_gbk {genome} --datadir {_data_dir(working_dir)} --custom {custom}"


# --- Stage 3: Load genome ---

def load_gbk_cmd(working_dir, folder_path, genome):
    gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz")
    return f"{PYTHON_BIN} {working_dir}/manage.py load_gbk {gbk_path} --overwrite --accession {genome} --datadir {working_dir}/data"


def sync_genome_metadata_cmd(working_dir, folder_path, genome):
    gbk_path = os.path.join(folder_path, f"{genome}.gbk.gz")
    return f"{PYTHON_BIN} {working_dir}/manage.py sync_genome_metadata {genome} {gbk_path}"


# --- Stage 4: FastTarget ---

def fasttarget_cmd(working_dir, genome, folder_path):
    return f"{PYTHON_BIN} {working_dir}/manage.py fast_command {genome} {folder_path} --datadir {_data_dir(working_dir)}"


# --- Stages 5-7, 19, 21: Score loading ---

def load_score_cmd(working_dir, genome, param):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore(_data_dir(working_dir))
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
    return f"{PYTHON_BIN} {working_dir}/manage.py load_score_values {genome} {tsv_file} --datadir {_data_dir(working_dir)} --overwrite"


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


# --- Stage 16: ESMFold (legacy, kept as fallback) ---

def esmfold_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py esmfold_predict {genome} --datadir {working_dir}/data"


# --- Stage 16: ColabFold (replaces ESMFold — no size limit, no external API dependency) ---

def colabfold_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py colabfold_predict {genome} --datadir {working_dir}/data"


# --- Stage 17: Structure loading sub-stages ---

def load_af_model_cmd(locus_tag, working_dir, folder_path):
    protein_pdb = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af.pdb")
    return f"{PYTHON_BIN} {working_dir}/manage.py load_af_model {locus_tag} {protein_pdb} {locus_tag} --overwrite --datadir {_data_dir(working_dir)}"


def run_fpocket_cmd(folder_path, locus_tag):
    locus_dir = os.path.abspath(os.path.join(folder_path, "alphafold", locus_tag))
    host_locus_dir = _host_bind_path(
        locus_dir,
        env_name="TPW_DATA_DIR",
        container_base="/app/targetpathogenweb/data",
    )
    pdb_path = os.path.join(locus_dir, f"{locus_tag}_af.pdb")
    fpocket_pdb_path = f"/work/{locus_tag}_af.pdb"
    fpocket_out = os.path.join(locus_dir, f"{locus_tag}_af_out")
    if not os.path.exists(pdb_path):
        return f"echo 'No structure PDB for {locus_tag}, skipping fpocket'"
    return (
        f"if [ -d {shlex.quote(fpocket_out)} ]; then "
        f"echo 'fpocket output already exists for {locus_tag}'; "
        f"elif command -v docker >/dev/null 2>&1; then "
        f"docker run --user $(id -u):$(id -g) --rm -i "
        f"-v {shlex.quote(host_locus_dir)}:/work "
        f"ezequieljsosa/fpocket fpocket -f {shlex.quote(fpocket_pdb_path)}; "
        f"else echo 'Docker not available for fpocket on {locus_tag}, skipping'; fi"
    )


def fpocket2json_cmd(folder_path, locus_tag):
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out")
    if os.path.exists(locustag_af):
        return f"{PYTHON_BIN} -m SNDG.Structure.FPocket 2json {locustag_af} | gzip > {locustag_af}/fpocket.json.gz"
    return f"echo 'No fpocket output for {locus_tag}, skipping'"


def load_pocket_cmd(folder_path, locus_tag, working_dir):
    locustag_af = os.path.join(folder_path, "alphafold", locus_tag, f"{locus_tag}_af_out", "fpocket.json.gz")
    if os.path.exists(locustag_af):
        return f"{PYTHON_BIN} {working_dir}/manage.py load_fpocket --pocket_json {locustag_af} {locus_tag} --datadir {_data_dir(working_dir)}"
    return f"echo 'No fpocket data for {locus_tag}, skipping'"


def p2rank2json_cmd(genome, locus_tag, working_dir):
    return f"{PYTHON_BIN} {working_dir}/manage.py p2rank_2_json {genome} {locus_tag} --datadir {_data_dir(working_dir)}"


def load_p2pocket_cmd(genome, locus_tag, working_dir):
    from bioseq.io.SeqStore import SeqStore
    ss = SeqStore(_data_dir(working_dir))
    p2pocket_json = ss.p2rank_json(genome, locus_tag)
    return f"{PYTHON_BIN} {working_dir}/manage.py load_fpocket --pocket_json {p2pocket_json} {locus_tag} --datadir {_data_dir(working_dir)} --P2rank_pocket"


# --- Stage 18: Druggability ---

def druggability_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py druggability_2_csv {genome} --datadir {_data_dir(working_dir)}"


# --- Stage 20: PSORT ---

def psort_cmd(genome, gram):
    folder_name = genome[int(len(genome) / 2 - 1):int(len(genome) / 2 + 2)]
    container_folder_path = os.path.join("/app/targetpathogenweb/data", folder_name, genome)
    host_folder_path = _host_bind_path(
        container_folder_path,
        env_name="TPW_DATA_DIR",
        container_base="/app/targetpathogenweb/data",
    )
    fallback = (
        f"{PYTHON_BIN} /app/targetpathogenweb/manage.py "
        f"tpweb_psort_fallback {shlex.quote(genome)} --datadir {_data_dir('/app/targetpathogenweb')}"
    )
    psort_script = (
        "set -e; "
        f"GENOME={shlex.quote(genome)}; "
        "if [ ! -s \"/work/$GENOME.faa\" ] && [ -s \"/work/$GENOME.faa.gz\" ]; then "
        "gzip -dc \"/work/$GENOME.faa.gz\" > \"/work/$GENOME.faa\"; "
        "fi; "
        "rm -f /work/*_psortb_*.txt /work/psort.tsv; "
        f"/usr/local/psortb/bin/psort -{shlex.quote(gram)} -o terse -i \"/work/$GENOME.faa\"; "
        "cp /tmp/results/*_psortb_*.txt /work/; "
        "RAW=$(ls -1 /work/*_psortb_*.txt | tail -n 1); "
        "awk -F '\\t' 'BEGIN{OFS=\"\\t\"; print \"gene\",\"Localization\"} "
        "NR>1 && NF>=2 {split($1,a,\" \"); print a[1],$2}' \"$RAW\" > /work/psort.tsv; "
        "chmod 0644 /work/psort.tsv"
    )
    return (
        f"if command -v docker >/dev/null 2>&1; then "
        f"docker run --rm --entrypoint /bin/sh "
        f"-v {shlex.quote(host_folder_path)}:/work "
        f"brinkmanlab/psortb_commandline:1.0.2 "
        f"-lc {shlex.quote(psort_script)}; "
        f"elif [ \"${{TPW_PSORT_ALLOW_FALLBACK:-0}}\" = \"1\" ]; then "
        f"{fallback}; "
        f"else echo 'Docker is required for PSORT; set TPW_PSORT_ALLOW_FALLBACK=1 to generate Unknown localization fallback.' >&2; exit 1; "
        f"fi"
    )


# --- Stages 22-23: Binders ---

def get_binders_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py get_binders {genome} --datadir {_data_dir(working_dir)}"


def load_binders_cmd(working_dir, genome):
    return f"{PYTHON_BIN} {working_dir}/manage.py load_binders {genome} --datadir {_data_dir(working_dir)}"

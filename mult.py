#!/usr/bin/env python3
import os
import argparse
import sys
import django
import math
import subprocess as sb
import gzip
import paramiko
import shutil
import json
import pandas as pd
from Bio import SeqIO

def manage_genome(genome, folder_name, folder_path):
    """Loads and indexes the genome

    Args:
        genome (str): Genome Accession number
    """
    my_env = os.environ.copy()
    gb_path = os.path.join(folder_path, f"{genome}.gbk.gz")
    sb.run(["python", "manage.py", "download_gbk", genome],
                env=my_env, check=True)
    if not os.path.exists(gb_path):
        sys.stderr.write("Genome file not found! Skipping execution!")
        pass
    sb.run(["python", "manage.py", "load_gbk",
                f"{gb_path}",  "--overwrite", "--accession", genome], env=my_env, check=True)
    sb.run(["python", "manage.py", "index_genome_db",
                genome], env=my_env, check=True)
    sb.run(["python", "manage.py", "index_genome_seq",
                genome], env=my_env, check=True)
    
def manage_proteins(genome, folder_name, folder_path):
    """Connects to a vpn to remotely execute the interproscan to get the protein families
    and downloads its results in the correct folder. Also load the results in the database

    Args:
        genome (str): Genome Accession number
    """
    my_env = os.environ.copy()
    """
    ssh_username = os.getenv('SSH_USERNAME')
    ssh_password = os.getenv('SSH_PASSWORD') # to do: talk about a way to decrypt an encrypted message
    ssh_rootfolder = ""
    ssh_host = ""
    #   need testing
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ssh_host, username=ssh_username, password=ssh_password)
    scp = ssh.open_sftp()
    scp.put(os.path.join(folder_path, genome + '.faa.tsv.gz'), ssh_rootfolder)
    stdin, stdout, stderr = ssh.exec_command(
        f"zcat NC_003047.faa.gz | interproscan.sh --pathways \
        --goterms --cpu 10 -iprlookup --formats tsv -i - --output-dir {ssh_rootfolder} -o {ssh_rootfolder}/NC_003047.faa.tsv"
    )
    stdout.channel.set_combine_stderr(True)
    output = stdout.readlines() #reading to stdout to force the wait on the command
    scp.get(f"{ssh_rootfolder}/NC_003047.faa.tsv", os.path.join(folder_path, genome))
    scp.close()
    ssh.close()
    """
    sb.run(["python", "manage.py", "load_interpro", genome,
            "--interpro_tsv", os.path.join(
        folder_path, genome + '.faa.tsv.gz')], env=my_env, check=True)

def get_alphafolds(genome, folder_name, folder_path):
    """Checks the mapped proteins and runs alphafold on each one of them.

    Args:
        genome (str): Genome Accession number
    """
    my_env = os.environ.copy()
    with open(os.path.join(folder_path, genome + '_unips.lst'), 'w+') as unip_lst:
        sb.run(["python", "manage.py", "gbk2uniprot_map", genome, "--mapping_tmp",
                    f"{os.path.join(folder_path, genome + '_unips_mapping.csv')}",
                    "--not_mapped",
                    f"{os.path.join(folder_path, genome + '_unips_not_mapped.lst')}"], env=my_env, check=True, stdout=unip_lst)
    with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
        sb.run(["python", "-m", "TP.alphafold", "-pr",
                "/opt/p2rank_2.4/prank", "-o", os.path.join(folder_path, "alphafold"), "-T", "10", "-nc"], env=my_env, check=True, input=unip_lst.read(), text=True)

def load_alphafold_structure(genome, folder_name, folder_path, protein_name, locus_tag):
    """Loads the structure of a desired protein

    Args:
        genome (str): Genome Accession number
        protein_name (str): Protein PDB code
        locus_tag (str): Strucure PDB code
    """
    my_env = os.environ.copy()
    locus_tag_fold = os.path.join(folder_path, locus_tag)
    sb.run(["python", "manage.py", "load_af_model", locus_tag, f"{os.path.join(folder_path, 'alphafold/' + protein_name + '/' + protein_name + '_AF.pdb')}",
                locus_tag, "--overwrite"], env=my_env, check=True)
    with gzip.open(os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), 'rb') as f_in:
        with open(os.path.join(locus_tag_fold, locus_tag + "_AF.pdb"), 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    sb.run(["python", "-m", "TP.alphafold", "-o", folder_path,
            "-T", "10", "-nc", "-np", "-na"], env=my_env, check=True, input=f"{locus_tag}", text=True)
    json_output = sb.run(["python", "-m", "SNDG.Structure.FPocket", "2json", os.path.join(locus_tag_fold, f"{locus_tag}_AF_out")],
            env=my_env, check=True, stdout=sb.PIPE)
    a = json.loads(json_output.stdout)
    zipped_content = gzip.compress(bytes(json.dumps(a), 'utf-8'))
    with open(os.path.join(locus_tag_fold, "fpocket.json.gz"), 'wb') as f:
        f.write(zipped_content)
    with open(os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), 'wb') as f2:
        f2.write(zipped_content)
    #echo -e "\n" | gzip >> data/003/NC_003047/SM_RS15270/SM_RS15270.pdb.gz
    filtered = list()
    with open(f"{locus_tag_fold}/{locus_tag}_AF_out/{locus_tag}_AF_out.pdb", 'r') as f:
        for line in f.readlines():
            if line[:6] == "HETATM" and "POL" in line and "STP" in line:
                filtered.append(line)
    filtered_str = ('').join(filtered)
    zipped_content = gzip.compress(bytes(filtered_str, 'utf-8'))
    with open(os.path.join(locus_tag_fold, locus_tag + ".pdb.gz"), 'ab') as f2:
        f2.write(zipped_content)

def run_pathwaytools(genome, folder_name, folder_path, orgdbname, domain, taxid):
    """Run pathwaytools in a genome

    Args:
        genome (str): Genome Accession number
        orgdbname (str): name of the organism in the database
        domain (str): domain of the genome
        taxid (str): taxonomic id of the genome
    """
    my_env = os.environ.copy()
    if not os.path.exists(os.path.join(folder_path, genome + ".gbk")): # the genbank file doesn't exist
        # extract the genbank file
        with gzip.open(os.path.join(folder_path, genome + ".gbk.gz"), 'rb') as f_in:
            with open(os.path.join(folder_path, genome + ".gbk", 'wb')) as f_out:
                shutil.copyfileobj(f_in, f_out)
    if not os.path.exists("./dbs/pathwaytools/"):
        os.makedirs("./dbs/pathwaytools/", exist_ok = True)
    sb.run(["python", "-m", "TP.pathoLogic", orgdbname, domain, taxid, "./dbs/pathwaytools/", os.path.abspath(folder_path),
            os.path.join(folder_path, "pathwaytools")], env=my_env, check=True)


def main(genomes):    
    my_env = os.environ.copy()
    for genome in genomes:
        acclen = len(genome)
        folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
        folder_path = f"./data/{folder_name}/{genome}"
        manage_genome(genome, folder_name, folder_path)
        manage_proteins(genome, folder_name, folder_path)
        get_alphafolds(genome, folder_name, folder_path)
        protein_ids = pd.read_csv(os.path.join(folder_path, f'{genome}_unips_mapping.csv'),
                                  sep = ',')
        #----------------------------------------------------
        mapped_proteins = list()
        with open(os.path.join(folder_path, f"{genome}_unips.lst"), 'r') as f:
            mapped_proteins = [x.strip() for x in f.readlines()]
        for record in SeqIO.parse(os.path.join(folder_path, f"{genome}.gbk"), "genbank"):
            for feature in record.features:
                if feature.type == "CDS":
                    locus_tag = feature.qualifiers["locus_tag"][0]
                    protein_id = feature.qualifiers["protein_id"][0]
                    entries = protein_ids.loc[(protein_ids["From"] == protein_id)]["Entry"].unique()
                    for e in entries:
                        if e in mapped_proteins:
                            load_alphafold_structure(genome, folder_name, folder_path, e, locus_tag)
        run_pathwaytools(genome, folder_name, folder_path, "teste", "TAX-2", "266834")
        """
        load_alphafold_structure(genome, folder_name, folder_path, "Q92MY5", "SM_RS12605")
        """



if __name__ == "__main__":
    genomes = list()
    parser = argparse.ArgumentParser()
    parser.add_argument('genomes', help="List of Genbank accession numbers for genomes, separated with new lines",
                        type=str,
                        nargs='*',
                        default=sys.stdin)
    args = parser.parse_args()
    for l in args.genomes:
        genomes.append(l.strip().upper())
    main(genomes)
"""
argumentos necesarios para correr todo el script:
 - genome AC number
 - struct name
 - pdb file from protein
 - orgdb name
 - domain
 - taxid
"""
#!/usr/bin/env python3
import os
import argparse
import sys
import django
import subprocess as sb
import gzip
import paramiko
import shutil
import json
def main(genomes):
    my_env = os.environ.copy()
    ssh_username = os.getenv('SSH_USERNAME')
    ssh_password = os.getenv('SSH_PASSWORD') # to do: talk about a way to decrypt an encrypted message
    ssh_rootfolder = ""
    ssh_host = ""
    for genome in genomes:
        folder_name = genome.split('_')[1][:3]
        folder_path = f"./data/{folder_name}/{genome}"
        gb_path = os.path.join(folder_path, f"{genome}.gbk.gz")
        sb.run(["python", "manage.py", "download_gbk", genome],
                   env=my_env, check=True)
        sb.run(["python", "manage.py", "load_gbk",
                   f"{gb_path}",  "--overwrite", "--accession", genome], env=my_env, check=True)
        sb.run(["python", "manage.py", "index_genome_db",
                   genome], env=my_env, check=True)
        sb.run(["python", "manage.py", "index_genome_seq",
                   genome], env=my_env, check=True)
        """
        #-----------------------------------------------------
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
        sb.run(["python", "manage.py", "load_interpro", genome,
                "--interpro_tsv", os.path.join(
            folder_path, genome + '.faa.tsv.gz')], env=my_env, check=True)
        #-----------------------------------------------------------
        """
        with open(os.path.join(folder_path, genome + '_unips.lst'), 'w+') as unip_lst:
            sb.run(["python", "manage.py", "gbk2uniprot_map", genome, "--mapping_tmp",
                        f"{os.path.join(folder_path, genome + '_unips_mapping.csv')}",
                        "--not_mapped",
                        f"{os.path.join(folder_path, genome + '_unips_not_mapped.lst')}"], env=my_env, check=True, stdout=unip_lst)
        with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
            sb.run(["python", "-m", "TP.alphafold", "-pr",
                    "/opt/p2rank_2.4/prank", "-o", os.path.join(folder_path, "alphafold"), "-T", "10", "-nc"], env=my_env, check=True, input=unip_lst.read(), text=True)
        protein_name = "Q92LQ0"
        other_protein = "SM_RS15270"
        other_protein_fold = os.path.join(folder_path, other_protein)
        sb.run(["python", "manage.py", "load_af_model", other_protein, f"{os.path.join(folder_path, 'alphafold/' + protein_name + '/' + protein_name + '_AF.pdb')}",
                    other_protein, "--overwrite"], env=my_env, check=True)
        with gzip.open(os.path.join(other_protein_fold, other_protein + ".pdb.gz"), 'rb') as f_in:
            with open(os.path.join(other_protein_fold, other_protein + "_AF.pdb"), 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        sb.run(["python", "-m", "TP.alphafold", "-o", folder_path,
                "-T", "10", "-nc", "-np", "-na"], env=my_env, check=True, input=f"{other_protein}", text=True)
        json_output = sb.run(["python", "-m", "SNDG.Structure.FPocket", "2json", os.path.join(other_protein_fold, f"{other_protein}_AF_out")],
               env=my_env, check=True, stdout=sb.PIPE)
        a = json.loads(json_output.stdout)
        zipped_content = gzip.compress(bytes(json.dumps(a), 'utf-8'))
        with open(os.path.join(other_protein_fold, "fpocket.json.gz"), 'wb') as f:
            f.write(zipped_content)
        with open(os.path.join(other_protein_fold, other_protein + ".pdb.gz"), 'wb') as f2:
            f2.write(zipped_content)
        #echo -e "\n" | gzip >> data/003/NC_003047/SM_RS15270/SM_RS15270.pdb.gz
        filtered = list()
        with open(f"{other_protein_fold}/{other_protein}_AF_out/{other_protein}_AF_out.pdb", 'r') as f:
            for line in f.readlines():
                if line[:6] == "HETATM" and "POL" in line and "STP" in line:
                    filtered.append(line)
        filtered_str = ('').join(filtered)
        zipped_content = gzip.compress(bytes(filtered_str, 'utf-8'))
        with open(os.path.join(other_protein_fold, other_protein + ".pdb.gz"), 'ab') as f2:
            f2.write(zipped_content)
        if not os.path.exists(os.path.join(folder_path, genome + ".gbk")): # the genbank file doesn't exist
            # extract the genbank file
            with gzip.open(os.path.join(folder_path, genome + ".gbk.gz"), 'rb') as f_in:
                with open(os.path.join(folder_path, genome + ".gbk", 'wb')) as f_out:
                    shutil.copyfileobj(f_in, f_out)
        sb.run(["python", "-m", "TP.pathoLogic", 'teste', "TAX-2", "266834", "./dbs/pathwaytools/", os.path.abspath(folder_path),
                os.path.join(folder_path, "pathwaytools")], env=my_env, check=True)
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
    main()
"""
argumentos necesarios para correr todo el script:
 - genome AC number
 - struct name
 - pdb file from protein
 - orgdb name
 - domain
 - taxid
"""
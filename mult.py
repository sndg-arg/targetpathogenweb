#!/usr/bin/env python3
import os
import argparse
import sys
import django
import subprocess as sb
import gzip

def main():
    my_env = os.environ.copy()
    genomes = list()
    parser = argparse.ArgumentParser()
    parser.add_argument('genomes', help="List of Genbank accession numbers for genomes, separated with new lines",
                        type=str,
                        nargs='*',
                        default=sys.stdin)
    args = parser.parse_args()
    for l in args.genomes:
        genomes.append(l.strip().upper())
    for genome in genomes:
        folder_name = genome.split('_')[1][:3]
        folder_path = os.path.join(os.getcwd(), f"data/{folder_name}/{genome}")
        gb_path = os.path.join(folder_path, f"{genome}.gbk.gz")
        sb.run(["python", "manage.py", "download_gbk", genome],
                   env=my_env, check=True)
        sb.run(["python", "manage.py", "load_gbk",
                   f"{gb_path}",  "--overwrite"], env=my_env, check=True)
        sb.run(["python", "manage.py", "index_genome_db",
                   genome], env=my_env, check=True)
        sb.run(["python", "manage.py", "index_genome_seq",
                   genome], env=my_env, check=True)
        # zcat data/003/NC_003047.faa.gz | interproscan.sh --pathways --goterms --cpu 10 -iprlookup --formats tsv -i - --output-dir ./ -o data/003/NC_003047.faa.tsv
        # gzip data/003/NC_003047.faa.tsv
        #sb.run(["python", "manage.py", "load_interpro", genome, os.path.join(
        #    folder_path, genome + '.faa.tsv.gz')], env=my_env, check=True)
        with open(os.path.join(folder_path, genome + '_unips.lst'), 'w+') as unip_lst:
            sb.run(["python", "manage.py", "gbk2uniprot_map", genome, "--mapping_tmp",
                        f"{os.path.join(folder_path, genome + '_unips_mapping.csv')}",
                        "--not_mapped",
                        f"{os.path.join(folder_path, genome + '_unips_not_mapped.lst')}"], env=my_env, check=True, stdout=unip_lst)
        with open(os.path.join(folder_path, genome + '_unips.lst'), 'r') as unip_lst:
            sb.run(["python", "-m", "TP.alphafold", "-pr",
                    "/opt/p2rank_2.4/prank", "-o", os.path.join(folder_path, "alphafold"), "-T", "10", "-nc"], env=my_env, check=True, input=unip_lst.read(), text=True)

        sb.run(["python", "-m", "TP.alphafold", "-o", f"{os.path.join(folder_path, 'SM_RS15270')}",
                "-T", "10", "-nc", "-np"], env=my_env, check=True, input="SM_RS15270.pdb_out", text=True)

        protein_name = "Q92LQ0"
        sb.run(["python", "manage.py", "load_af_mode\l", "SM_RS15270", f"{os.path.join(folder_path, protein_name + '/' + protein_name + '_AF.pdb')}",
                    "SM_RS15270", "--overwrite"], env=my_env, check=True)
        json_output = sb.run(["python", "-m", "SNDG.Structure.FPocket", "2json", f"{folder_path}/SM_RS15270/SM_RS15270.pdb_out/SM_RS15270/SM_RS15270.pdb_out.pdb"],
               env=my_env, check=True, stdout=sb.PIPE)
        zipped_content = gzip.compress(bytes(json_output.stdout.read(), 'utf-8'))
        with open(f"{folder_name}/SM_RS15270/fpocket.json.gz", 'wb') as f:
            f.write(zipped_content)
        #echo -e "\n" | gzip >> data/003/NC_003047/SM_RS15270/SM_RS15270.pdb.gz
        # we should filter only pockets with druggability > 0.2
        filtered = list()
        with open(f"{folder_name}/SM_RS15270/SM_RS15270.pdb_out/SM_RS15270.pdb_out.pdb", 'r') as f:
            for line in f.readlines():
                if line[:6] == "HETATM" and "POL" in line and "STP" in line:
                    filtered.append(line)
                    filtered_str = ('\n').join(filtered)
        zipped_content = gzip.compress(bytes(filtered_str, 'utf-8'))
        with open(f"{folder_name}/SM_RS15270/SM_RS15270.pdb.gz", 'wb') as f2:
            f2.write(zipped_content)

if __name__ == "__main__":
    main()

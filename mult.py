#!/usr/bin/env python3
import os, argparse, sys
import django
import subprocess as sb
def main():
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
        path = os.path.join(os.getcwd(),f"data/{folder_name}/{genome}.tar.gz")
        o = sb.check_output(["python", "manage.py", "download_gbk", f"{genome} | gzip"])
        print(o)
        sb.check_output(["python", "manage.py", "load_gbk", f"{path} --overwrite"])
        sb.check_output(["python", "manage.py", "index_genome_db", f"{genome}"])
        sb.check_output(["python", "manage.py", "index_genome_seq", f"{genome}"])





if __name__ == "__main__":
    main()
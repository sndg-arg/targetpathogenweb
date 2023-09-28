#!/usr/bin/env python3
import os, argparse, sys
import subprocess as sb
import django
from django.core import management
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
        management.call_command("download_gbk", f"{genome} | gzip", verbosity=1, interactive=False)
        management.call_command("load_gbk", f"{path} --overwrite", verbosity=1, interactive=False)
        management.call_command("index_genome_db", f"{genome}", verbosity=1, interactive=False)
        management.call_command("index_genome_seq", f"{genome}", verbosity=1, interactive=False)




if __name__ == "__main__":
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tpwebconfig.settings')
    main()
#!/usr/bin/env python3
import os, argparse, sys
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
    shell_script_text = "#!/bin/bash\n"
    for genome in genomes:
        folder_name = genome.split('_')[1][:3]
        path = os.path.join(os.getcwd(),f"data/{folder_name}/{genome}.tar.gz")
        shell_script_text += (f"./manage.py download_gbk {genome} | gzip\n")
        shell_script_text += (f"./manage.py load_gbk {path} --overwrite\n")
        shell_script_text += (f"./manage.py index_genome_db {genome}\n")
        shell_script_text += (f"./manage.py index_genome_seq {genome}\n")
    print(shell_script_text)
    with open("script.sh", 'w+') as script:
        script.write(shell_script_text)
    os.chmod("script.sh", 775)
    p = sb.Popen("./script.sh")
    p.wait()


if __name__ == "__main__":
    main()
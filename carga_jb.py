#!/usr/bin/env python

import os
import subprocess
from tqdm import tqdm


# Directorio base donde se encuentran los datos de los genomas
data_dir = os.getenv('JBROWSE_DATA_DIR')

# Función para convertir una ruta del host a una ruta del contenedor
def docker_path(host_path):
    return host_path.replace(data_dir, "/data")

# Iterar sobre cada subdirectorio de genoma, considerando la nueva estructura
for root, dirs, files in os.walk(data_dir):
    for dir_name in tqdm(dirs, desc="Procesando directorios de genoma"):
        sub_path = os.path.join(root, dir_name)
        for sub_dir_name in tqdm(os.listdir(sub_path), desc=f"Procesando subdirectorios en {dir_name}"):
            genome_path = os.path.join(sub_path, sub_dir_name)
            if os.path.isdir(genome_path):  # Asegurarse de que es un directorio
                config_path = os.path.join(genome_path, 'config.json')
                
                # Verificar si el archivo config.json ya existe en el directorio
                if not os.path.isfile(config_path):
                    # Los nombres de archivos se basan directamente en el nombre del directorio
                    genome_id = sub_dir_name

                    fna_bgz_file = f'{genome_id}.genome.fna.bgz'
                    gff_bgz_file = f'{genome_id}.gff.bgz'

                    fna_bgz_path = os.path.join(genome_path, fna_bgz_file)
                    gff_bgz_path = os.path.join(genome_path, gff_bgz_file)

                    # Verificar la existencia de los archivos antes de ejecutar los comandos
                    if os.path.exists(fna_bgz_path) and os.path.exists(gff_bgz_path):
                        assembly_command = [
                            'docker', 'run', '-v', f'{data_dir}:/data', '--rm', '-u', f'{os.getuid()}:{os.getgid()}', 'jbrowse',
                            'jbrowse', 'add-assembly', docker_path(fna_bgz_path),
                            '--load', 'inPlace', '--out', docker_path(genome_path), '--type', 'bgzipFasta'
                        ]

                        track_command = [
                            'docker', 'run', '-v', f'{data_dir}:/data', '--rm', '-u', f'{os.getuid()}:{os.getgid()}', 'jbrowse',
                            'jbrowse', 'add-track', docker_path(gff_bgz_path),
                            '--load', 'inPlace', '--out', docker_path(genome_path), '--assemblyNames', genome_id
                        ]

                        # Ejecutar los comandos
                        subprocess.run(assembly_command)
                        subprocess.run(track_command)
                    else:
                        print(f"No se encontraron los archivos para {genome_id} en {genome_path}")
                else:
                    print(f"config.json ya existe en {genome_path}, omitiendo...")

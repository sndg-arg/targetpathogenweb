#!/bin/bash

# Directorio base donde se encuentran los datos de los genomas
DATA_DIR=~/Desktop/target/targetpathogenweb/data

# Directorio de JBrowse
JBROWSE_DIR=~/Desktop/target/targetpathogenweb/js/jbrowse

# Iterar sobre cada subdirectorio de genoma
for genome_path in $DATA_DIR/*/*; do
    # Extraer el identificador único del genoma del nombre del directorio
    genome_id=$(basename "$genome_path")

    # Comando para agregar la asamblea del genoma
    docker run -v $DATA_DIR:/data --rm -u $(id -u):$(id -g) -v $JBROWSE_DIR:/jbrowse jbrowse \
    jbrowse add-assembly /data/${genome_path#$DATA_DIR/}/${genome_id}.genome.fna.bgz \
    --load copy --out /jbrowse/data/${genome_id}/ --type bgzipFasta

    # Comando para agregar el track de anotaciones (GFF)
    docker run -v $DATA_DIR:/data --rm -u $(id -u):$(id -g) -v $JBROWSE_DIR:/jbrowse jbrowse \
    jbrowse add-track /data/${genome_path#$DATA_DIR/}/${genome_id}.gff.bgz \
    --load copy --out /jbrowse/data/${genome_id}/
done

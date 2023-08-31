FROM continuumio/miniconda3:4.11.0
LABEL authors="eze"

WORKDIR /app

RUN conda create -n tpv2 -c conda-forge -c bioconda python=3.10 samtools blast bedtools bcftools
RUN conda activate tpv2

RUN pip install -r requirements/base.txt
RUN pip install -r requirements/dev.txt


SHELL ["conda", "run", "-n", "tpv2", "/bin/bash", "-c"]



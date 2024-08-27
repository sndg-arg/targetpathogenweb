FROM continuumio/miniconda3:4.11.0
LABEL authors="eze"

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    wget \
    vim \
    libbz2-dev \
    libpq-dev \
    libcurl4-openssl-dev \
    libgsl0-dev \
    liblzma-dev \
    libncurses5-dev \
    libperl-dev \
    libssl-dev \
    zlib1g-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Clone the necessary repositories
RUN git clone https://github.com/ezequieljsosa/sndg-bio.git \
    && git clone https://github.com/sndg-arg/targetpathogen.git \
    && git clone https://github.com/sndg-arg/sndgjobs.git \
    && git clone https://github.com/sndg-arg/sndgbiodb.git \
    && git clone https://github.com/sndg-arg/targetpathogenweb.git

# Install Docker CLI
ENV docker_url=https://download.docker.com/linux/static/stable/x86_64
ENV docker_version=19.03.12
RUN curl -fsSL $docker_url/docker-$docker_version.tgz | tar zxvf - --strip 1 -C /usr/bin docker/docker


RUN conda create -n tpv2 -c conda-forge -c bioconda python=3.10 samtools blast bedtools bcftools

COPY requirements.txt .
COPY start.sh .

SHELL ["conda", "run", "-n", "tpv2", "/bin/bash", "-c"]

RUN pip install -r requirements.txt


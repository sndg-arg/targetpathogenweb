FROM continuumio/miniconda3:4.11.0
LABEL authors="eze"

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}
ENV no_proxy=${NO_PROXY}

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
    bioperl \
    bioperl-run \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Download and install JDK 17 for the current image architecture.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) jdk_arch="x64" ;; \
      arm64) jdk_arch="aarch64" ;; \
      *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    curl -sL "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.12%2B7/OpenJDK17U-jdk_${jdk_arch}_linux_hotspot_17.0.12_7.tar.gz" | tar -xz -C /opt
ENV JAVA_HOME=/opt/jdk-17.0.12+7
ENV PATH=${JAVA_HOME}/bin:${PATH}

# Restore the Docker CLI because TP.alphafold and TP.psort shell out to
# `docker run ...` for fpocket/PSORT execution.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) docker_arch="x86_64" ;; \
      arm64) docker_arch="aarch64" ;; \
      *) echo "Unsupported Docker CLI architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    docker_url="https://download.docker.com/linux/static/stable/${docker_arch}/docker-19.03.12.tgz"; \
    curl -fsSL "${docker_url}" | tar -xz -C /usr/local/bin --strip-components=1 docker/docker

# Clone Python dependencies that are imported via PYTHONPATH at runtime.
RUN git clone --depth 1 https://github.com/ezequieljsosa/sndg-bio.git /app/sndg-bio \
    && git clone --depth 1 https://github.com/sndg-arg/targetpathogen.git /app/targetpathogen \
    && git clone --depth 1 https://github.com/sndg-arg/sndgjobs.git /app/sndgjobs \
    && git clone --depth 1 https://github.com/sndg-arg/sndgbiodb.git /app/sndgbiodb \
    && ln -s /app/targetpathogen /app/target

RUN conda create -n tpv2 -c conda-forge -c bioconda python=3.10 samtools blast bedtools bcftools setuptools requests urllib3 xmltodict python-libsbml ncbi-datasets-cli pyyaml

COPY requirements.txt /tmp/requirements.txt

SHELL ["conda", "run", "-n", "tpv2", "/bin/bash", "-c"]

RUN pip install --no-cache-dir "setuptools==68.2.2" \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY fasttarget_mac /app/fasttarget
COPY opt /app/opt
COPY . /app/targetpathogenweb

RUN rm -rf /app/fasttarget/logs /app/fasttarget/organism \
    && mkdir -p /app/fasttarget/logs /app/fasttarget/organism \
    && find /app -type d -name .git -prune -exec rm -rf {} +

WORKDIR /app/targetpathogenweb

ENV PYTHONPATH=/app/sndgjobs:/app/sndgbiodb:/app/targetpathogen:/app/sndg-bio:/app/target:/app/targetpathogenweb

# Run as non-root user. The docker group GID is set to match the host's
# docker socket so that fpocket/PSORT Docker-in-Docker still works.
ARG DOCKER_GID=999
RUN groupadd -g ${DOCKER_GID} docker || true \
    && useradd -m -s /bin/bash -G docker appuser \
    && chown -R appuser:appuser /app \
    && chmod -R a+rX /opt/conda

USER appuser

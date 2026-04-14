# =============================================================================
# Stage 1: Builder — conda env, pip deps, JDK, Docker CLI
# =============================================================================
FROM continuumio/miniconda3:4.11.0 AS builder
LABEL authors="eze"

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

WORKDIR /build

# System build deps (only needed for compilation, not runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libbz2-dev \
    libpq-dev \
    libcurl4-openssl-dev \
    libgsl0-dev \
    liblzma-dev \
    libncurses5-dev \
    libperl-dev \
    libssl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Conda environment
RUN conda create -n tpv2 -c conda-forge -c bioconda \
    python=3.10 samtools blast bedtools bcftools setuptools requests \
    urllib3 xmltodict python-libsbml ncbi-datasets-cli pyyaml \
    && conda clean -afy

# Pip deps inside conda env
COPY requirements.txt /tmp/requirements.txt
SHELL ["conda", "run", "-n", "tpv2", "/bin/bash", "-c"]
RUN pip install --no-cache-dir "setuptools==68.2.2" \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# JDK 17 (needed at runtime for InterProScan)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) jdk_arch="x64" ;; \
      arm64) jdk_arch="aarch64" ;; \
      *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    curl -sL "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.12%2B7/OpenJDK17U-jdk_${jdk_arch}_linux_hotspot_17.0.12_7.tar.gz" \
    | tar -xz -C /opt

# Docker CLI (for fpocket/PSORT Docker-in-Docker)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64) docker_arch="x86_64" ;; \
      arm64) docker_arch="aarch64" ;; \
      *) echo "Unsupported Docker CLI architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-19.03.12.tgz" \
    | tar -xz -C /usr/local/bin --strip-components=1 docker/docker

# Clone Python deps (shallow, strip .git to save space)
RUN git clone --depth 1 https://github.com/ezequieljsosa/sndg-bio.git /app/sndg-bio \
    && git clone --depth 1 https://github.com/sndg-arg/targetpathogen.git /app/targetpathogen \
    && git clone --depth 1 https://github.com/sndg-arg/sndgjobs.git /app/sndgjobs \
    && git clone --depth 1 https://github.com/sndg-arg/sndgbiodb.git /app/sndgbiodb \
    && git clone --depth 1 https://github.com/L-G-g/fasttarget.git /app/fasttarget \
    && ln -s /app/targetpathogen /app/target \
    && find /app -type d -name .git -prune -exec rm -rf {} +


# =============================================================================
# Stage 2: Runtime — only what's needed to run the application
# =============================================================================
FROM continuumio/miniconda3:4.11.0 AS runtime

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

WORKDIR /app

# Runtime-only system packages (no build-essential, no git, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    libcurl4 \
    libgsl25 \
    postgresql-client \
    bioperl \
    bioperl-run \
    && rm -rf /var/lib/apt/lists/*

# Copy conda env from builder
COPY --from=builder /opt/conda /opt/conda

# Copy JDK
COPY --from=builder /opt/jdk-17.0.12+7 /opt/jdk-17.0.12+7
ENV JAVA_HOME=/opt/jdk-17.0.12+7
ENV PATH=${JAVA_HOME}/bin:${PATH}

# Copy Docker CLI
COPY --from=builder /usr/local/bin/docker /usr/local/bin/docker

# Copy Python library clones
COPY --from=builder /app/sndg-bio /app/sndg-bio
COPY --from=builder /app/targetpathogen /app/targetpathogen
COPY --from=builder /app/sndgjobs /app/sndgjobs
COPY --from=builder /app/sndgbiodb /app/sndgbiodb
COPY --from=builder /app/target /app/target

# Copy fasttarget from builder
COPY --from=builder /app/fasttarget /app/fasttarget

# Copy application code
COPY . /app/targetpathogenweb

RUN rm -rf /app/fasttarget/logs /app/fasttarget/organism \
    && mkdir -p /app/fasttarget/logs /app/fasttarget/organism \
    && chmod +x /app/targetpathogenweb/start.sh /app/targetpathogenweb/start_queue.sh

WORKDIR /app/targetpathogenweb

ENV PYTHONPATH=/app/sndgjobs:/app/sndgbiodb:/app/targetpathogen:/app/sndg-bio:/app/target:/app/targetpathogenweb

# Non-root user with Docker group access for DinD
ARG DOCKER_GID=999
RUN groupadd -g ${DOCKER_GID} docker || true \
    && useradd -m -s /bin/bash -G docker appuser \
    && chown -R appuser:appuser /app \
    && chmod -R a+rX /opt/conda

USER appuser

# Graceful shutdown: Docker sends SIGTERM, queue worker handles it
STOPSIGNAL SIGTERM

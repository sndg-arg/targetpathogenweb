
# **FastTarget Setup Instructions**

## 🚀 Quick Start

**Want to get started quickly?** Follow these minimal steps:

1. **Clone and setup environment:**
   ```bash
   git clone https://github.com/mcpalumbo/fasttarget.git
   cd fasttarget
   conda env create -f requirements.yml
   conda activate fasttarget
   bash setup_docker.sh  # or setup_containers.sh for apptainer/singularity
   ```

2. **Download databases:**

   **[Download pre-built databases here](LINK_TO_PREBUILT_DATABASES)**

   Simply extract the downloaded file into your `fasttarget/` directory.
   Or download with: 

   ```bash
   python databases.py --download all # or the database of choice
   ```
   *Note: This downloads ~30GB of data and may take time.*

3. **Prepare your config file:**
   - Copy `config.yml` and edit the essential fields:
     - `organism.name` (e.g., `PAO1`)
     - `organism.tax_id` (e.g., `287` for *P. aeruginosa*)
     - `organism.strain_taxid` (e.g., `208964`)
     - `organism.gbk_file` (path to your GenBank file)
     - Enable/disable modules as needed

4. **Run the pipeline:**
   ```bash
   python fasttarget.py --config_file your_config.yml
   ```

5. **Results:**
   - Find your results in `organism/your_organism_name/your_organism_name_results_DATE/`
   - Main output: `your_organism_name_results_table.tsv`

📖 **Need more details?** Continue reading the comprehensive documentation below.

> **Note:** Resource usage varies with organism size and enabled modules. The heaviest steps are typically colabfold, offtarget.foldseek_human, and offtarget.microbiome (large databases and long runtimes). Core-genome conservation (core) can also become one of the heaviest steps when many genomes are pulled for your taxon; the number of genomes depends on how many assemblies are deposited in NCBI. In practice, FastTarget runs on a mid-range workstation (e.g., Ryzen 5 with 32 GB RAM); very old or low-memory machines may struggle with heavy modules.

---

## Table of Contents

- [Overview](#overview)
- [Detailed Setup Instructions](#detailed-setup-instructions)
  - [Conda Environment Setup](#conda-environment-setup)
  - [Container Images](#container-images)
  - [ColabFold Installation (Optional)](#colabfold-installation-optional)
- [Databases Setup](#databases-setup)
- [Test Case](#test-case)
- [Configuration File Guide](#editing-the-configyml-file)
- [Running FastTarget](#running-the-fasttarget-pipeline)
- [Output Reference](#understanding-output-columns)
- [Running with Nextflow (HPC)](#running-nextflow)
- [Troubleshooting](#troubleshooting-and-tips)
- [Key Files and Components](#key-files-and-components)

---

## Overview


**FastTarget** is a modular pipeline to prioritize bacterial drug targets, combining:
- **Metabolic network analysis** (*Pathway Tools* or *SBML + MetaGraphTools*)
- **Structural analysis** (*UniProt mapping*, *PDB/AlphaFold* download, pocket detection)
- **Core-genome conservation** (*Roary* / *CoreCruncher*)
- **Offtarget screening** (*human proteome*, *gut microbiome*, *Foldseek*)
- **Essentiality checks** (*DEG*)
- **Localization** (*PSORTb*)
- **User metadata merging** and final results export

### Execution Modes

FastTarget can be executed in two alternative ways:

**1. Standalone (local execution)**
   - Python driver: `fasttarget.py`
   - Runs the entire pipeline from the command line on a local machine
   - **Recommended if you:**
      - Want to test the pipeline
      - Are working with small datasets
      - Are running FastTarget on a personal computer or single server

**2. HPC / Cluster execution**
   - Nextflow workflow: `nextflow/main.nf`
   - Designed for high-performance computing (HPC) environments
   - **Recommended if you:**
      - Run large datasets
      - Use an HPC cluster
      - Need parallel execution for speed and scalability

> Both execution modes use the same analysis code and configuration file format: `config.yml`

---

## Detailed Setup Instructions

Dependencies are split between the conda environment and containers. The conda environment provides Python and core libraries; external bioinformatics tools are executed via Docker/Singularity containers unless explicitly noted (e.g., ColabFold).

### Conda Environment Setup

To set up the conda environment for this project, follow these steps:

1. **Create the conda environment:**
   ```bash
   conda env create -f requirements.yml
   ```

2. **Activate the conda environment:**
   ```bash
   conda activate fasttarget
   ```

### Container Images

This project requires the use of **container images** to run specific bioinformatics tools.

- For **standalone** use: available with **Docker** or **Singularity**.
- For **Nextflow**: available only with **Singularity**.

Pull container images using the provided scripts:

```bash
# Docker images
bash setup_docker.sh

# Singularity images (if preferred or Nextflow)
bash setup_containers.sh
```

> **Note:** This pipeline is designed to run Docker commands without `sudo`.

To set up Docker so that `sudo` is not required, follow these steps:

1. **Create the Docker group** (if it doesn't already exist):
   ```bash
   sudo groupadd docker
   ```
2. **Add your user to the Docker group** (replace `your-username`):
   ```bash
   sudo usermod -aG docker your-username
   ```
3. **Log out and log back in** for the changes to take effect.

After completing these steps, you will be able to run Docker commands without needing to prepend `sudo`.

> ⚠️ **Warning:**
> If you have Docker Desktop installed, this solution may not work and could result in errors. Certain configurations with Docker Desktop can lead to issues.

### ColabFold Installation (Optional)

**ColabFold is not automatically installed** by this pipeline. Unlike other bioinformatics tools that run through containers or are included in the fasttarget conda environment, ColabFold must be **manually installed** if you want to use AI-based structure prediction.

**When do you need ColabFold?**
- Only if you plan to use `colabfold.enabled: True` in your `config.yml`
- For generating AlphaFold2 models of proteins without available structures

**Installation steps:**

1. Follow the official ColabFold installation instructions: [https://github.com/sokrypton/ColabFold](https://github.com/sokrypton/ColabFold)

2. Verify that `colabfold_batch` is accessible in your PATH:
   ```bash
   which colabfold_batch
   ```
   
   This command should return the path to the ColabFold executable. If it doesn't, you need to add ColabFold to your PATH or the pipeline will fail when trying to run structure prediction.

> 💡 **Tip:** If you don't need structure prediction or already have sufficient structures from PDB/AlphaFold databases, you can skip ColabFold installation entirely and set `colabfold.enabled: False` in your config.


## Databases Setup


> **IMPORTANT:** You must have the required databases **BEFORE** running the FastTarget pipeline. The databases are not automatically downloaded during pipeline execution.

### Two Ways to Get the Databases

You have **two options** to obtain the necessary databases:

#### **Option 1: Download Pre-built Databases (Fastest)**

If you want to **save time** and get started quickly, you can download a ready-to-use database package:

📦 **[Download pre-built databases here](LINK_TO_PREBUILT_DATABASES)**

Simply extract the downloaded file into your `fasttarget/` directory. This package includes:
- Human proteome (UP000005640) - sequences and structures
- DEG database (essential genes)
- UHGP microbiome catalog

> **Note:** This option gives you a stable, tested version of all databases. However, these databases may not reflect the very latest updates from UniProt or other sources. If you download Option 1 you can ignore Option 2, and jump to the following section.

#### **Option 2: Download/Update Databases with Python Script (Latest Version)**

If you want the **most up-to-date** versions of the databases, use the `databases.py` script:

> **Download all databases (recommended):**
```bash
python databases.py --download all
```

> **Download individual databases:**
```bash
# Only human proteome sequences (FASTA)
python databases.py --download human-sequences

# Only human structures (PDB/AlphaFold - needed for Foldseek)
python databases.py --download human-structures

# Only microbiome catalogue
python databases.py --download microbiome

# Only DEG database
python databases.py --download deg
```

> **Optional parameters:**
```bash
# Specify custom database location
python databases.py --download all --database-path /path/to/databases

# Control number of parallel downloads
python databases.py --download all --cpus 8
```

### Required Databases


This repository uses several key databases for analysis:

1. **Human Proteome from UniProt (UP000005640):**
   - The complete *Homo sapiens* proteome including all annotated proteins.
   - Human PDB or AlphaFold structures for use with Foldseek.
   - **Note:** Requires over **20GB** of storage space.

2. **Database of Essential Genes (DEG):**
   - Contains essential bacterial genes from [DEG](http://origin.tubic.org/deg/public/index.php/download).
   - **Size:** ~500MB.

3. **Human Gut Microbiome Species Catalogue (v2.0.2):**
   - Individual genome sequences from the [MGnify Human Gut Microbiome Species Catalogue](https://www.ebi.ac.uk/metagenomics/genome-catalogues/human-gut-v2-0-2).
   - Contains representative genomes from gut microbial species.
   - Used to identify proteins present in the human gut microbiome.
   - **Size:** Over 7GB.

> **Total Storage Required:** ~30GB+ of free disk space.

**Which databases do you need?**
- For **human offtarget analysis** (BLASTp) → download `human-sequences`
- For **microbiome offtarget analysis** → download `microbiome`
- For **DEG essentiality analysis** → download `deg`
- For **Foldseek structural comparison** against human → download `human-structures`

### About the Human PDB/AlphaFold Index

The repository includes a **pre-calculated CSV file** (`databases/human_pdb_index_all_2026_01.csv`) that maps human proteins to their PDB and AlphaFold structures according to Uniprot 2026-01 release. This file is ready to use and works with the pre-built databases.

You only need to rebuild the index if you want the **latest UniProt release** before downloading with `databases.py --download human-structures` 

**How to rebuild the index:**

```bash
python ftscripts/build_human_pdb_index.py
```

This script will:
1. Query UniProt for the latest human protein entries
2. Fetch PDB and AlphaFold structure information
3. Generate a new CSV index file in `databases/`

> ⏱️ **Note:** Building the index can take several hours depending on your internet connection and UniProt server response times. Only run this if you need the absolute latest structure mappings.

## Test Case

> ### 🧪 **Test Case**

To test the pipeline, we provide only 20 proteins from the small genome of *Mycoplasma pneumoniae*.
This dataset includes the GenBank (GBK) file and the SBML file for metabolism analysis. 
You can find the test dataset in the `organism/test` folder.

> **Note:** The test suite requires the databases to be downloaded first. Make sure to run `python databases.py --download all` before testing. If you want to test the pipeline without downloading large databases, you can disable database-dependent modules in your `config_test.yml`, and only test the modules you are interested in.

**1. Run the pipeline with the test dataset:**
```bash
python fasttarget.py --config_file config_test.yml
```

**2. Validate the test output:**
After running the test, you can validate the results using:
```bash
python validate_test.py --test_dir organism/test
```

## Editing the `config.yml` File


The `config.yml` file is the **central configuration file** for this repository. It allows you to specify various settings related to your organism, CPU usage, structural data, metabolism, core genome analysis, offtarget analysis, DEG (Database of Essential Genes) analysis, localization, and metadata. Follow these steps to correctly fill out this file:

1. **Organism Information:**
   - `organism.name`: Enter a short alias/name for your genome without spaces or symbols. Example: `PAO1`.
   - `organism.tax_id`: Fill in the NCBI Taxonomy ID of your organism's species. Example: `287` for *Pseudomonas aeruginosa*. This is used to obtain the genomes for calculating the core genome.
   - `organism.strain_taxid`: Fill in the NCBI Taxonomy ID of the specific strain. Example: `208964` for *Pseudomonas aeruginosa* PAO1. This is used for structure analysis to map strain-specific proteins.
   - `organism.gbk_file`: Provide the path to the GenBank (GBK) file of your genome.

2. **CPU Usage Preferences:**
   - `cpus`: Specify the number of CPUs to be used for running this pipeline. Use `null` for auto-detection, or specify a number (e.g., `4`, `8`, `16`).

3. **Container Engine:**
   - `container_engine`: Choose `docker`, `singularity`, or `apptainer` for running containerized tools. Make sure to run the appropriate setup script (`setup_docker.sh` or `setup_containers.sh`) before using.

4. **Structures:**
   - `structures.enabled`: Set to `True` if structural data is to be used; otherwise, set to `False`.
   - `structures.proteome_uniprot`: Complete with the UniProt proteome ID for your organism. Example: `UP000002438` for *Pseudomonas aeruginosa* PAO1.
   - `structures.pocket_full_mode`: Set to `True` to find pockets in all structures for each protein (not only the best one). Note: This significantly increases runtime and resource usage.

   **Understanding Reference Structure:**
   
   A **reference structure** is the single best structure selected for each protein based on quality criteria:
   - For **PDB structures**: Selected based on resolution (≤3.5Å) and coverage (>40%) with X-ray preferred over EM
   - For **AlphaFold structures**: Used when no suitable PDB structure meets the criteria
   - For **ColabFold models**: Used when enabled and no other structures are available
   
   **Pocket Detection Modes:**
   
   - **Standard mode** (`pocket_full_mode: False`):
     - Analyzes pockets only in the **reference structure** (fastest)
     - Returns a single structure ID and its best pocket
     - Recommended for most cases
   
   - **Full mode** (`pocket_full_mode: True`):
     - Analyzes pockets in **all available structures** for each protein
     - Identifies the structure with the best pocket among all
     - Useful for comprehensive pocket comparison across multiple structures
     - **Warning:** Significantly increases computation time and storage requirements

5. **ColabFold (AI-based structure prediction):**
   - `colabfold.enabled`: Set to `True` to generate AlphaFold2 models using ColabFold for proteins without structures.
   - `colabfold.amber`: Set to `True` to perform Amber refinement on ColabFold models (improves accuracy but slower).
   - `colabfold.gpu`: Set to `True` to use GPU acceleration for ColabFold model generation.
   - `colabfold.colabfold_run_all`: Set to `True` to run ColabFold for all proteins, not only those without structures.

6. **Core Genome Analysis:**
   - `core.enabled`: Set to `True` if core genome analysis is required; otherwise, set to `False`.
   - `core.roary`: Enable Roary for core genome analysis by setting this to `True`.
   - `core.corecruncher`: Enable CoreCruncher by setting this to `True`.
   - `core.min_identity`: Minimum percentage identity for core genome analysis (0-100). Example: `95` for 95% identity.
   - `core.min_core_freq`: Minimum frequency for a gene to be considered core (0-100). Example: `99` means gene must be present in 99% of genomes.

7. **Metabolism:**
   
   **Option A: Using Pathway Tools files (metabolism-PathwayTools):**
   - `metabolism-PathwayTools.enabled`: Set to `True` if you have Pathway Tools output files.
   - Provide paths to your SBML file, chokepoint file, and smarttable file.
   - **Note:** To get help on how to generate these files, please read the tutorials in the `tutorial` folder.
   
   **Option B: Using only SBML file (metabolism-SBML):**
   - `metabolism-SBML.enabled`: Set to `True` if you only have an SBML file (no Pathway Tools files).
   - Provide path to your SBML file.
   - Optionally provide a filter file (TSV format) to exclude ubiquitous compounds from graph generation.
   - Uses MetaGraphTools Docker container to analyze the metabolic network.
   - **Note:** This is useful if you prefer to use an external SBML instead of a Pathway Tools automatically generated model.
   - ⚠️ **IMPORTANT:** Gene IDs in your SBML file must match the locus tags in your GenBank file for correct mapping. Inconsistent gene identifiers will result in failed mapping and missing data in the final results.

8. **Offtarget Analysis:**
   - `offtarget.enabled`: Set to `True` to enable offtarget analysis.
   - `offtarget.human`: Set to `True` to enable human offtarget analysis.
   - `offtarget.microbiome`: Set to `True` to enable microbiome offtarget analysis.
   - `offtarget.microbiome_identity_filter`: Filter value of % identity, only hits with higher values will be used. Recommended: `30-50`.
   - `offtarget.microbiome_coverage_filter`: Filter value of query coverage, only hits with higher values will be used. Recommended: `50-80`.
   - `offtarget.foldseek_human`: Set to `True` to use Foldseek for structural comparison against human proteome. **Note:** Requires both `offtarget.enabled` AND `structures.enabled` to be `True`.

9. **DEG Analysis:**
   - `deg.enabled`: Set to `True` to enable DEG analysis.
   - `deg.deg_identity_filter`: Filter value of % identity, only hits with higher values will be used. Recommended: `30-60`.
   - `deg.deg_coverage_filter`: Filter value of query coverage, only hits with higher values will be used. Recommended: `50-80`.

10. **Localization:**
   - `psortb.enabled`: Set to `True` to enable localization analysis.
   - `psortb.gram_type`: Specify the gram type: `n` (Gram-negative), `p` (Gram-positive), or `a` (archaea).

11. **Metadata:**
   - `metadata.enabled`: Set to `True` if you have additional metadata tables to include.
   - Provide a list of paths to your metadata tables under `meta_tables`.
   - **Format requirements:**
     - Files must be in TSV (tab-separated) or CSV (comma-separated) format
     - Must contain a header row with column names
     - **REQUIRED:** First column must be named `gene` and contain locus tags that match those in your GenBank file
     - Additional columns can contain any metadata you want to include (e.g., gene names, annotations, expression values, functional categories)
     - Example:
       ```
       gene            gene_name    function
       MPN_RS02380     alaS         Alanine--tRNA ligase
       MPN_RS02220     apt          Adenine phosphoribosyltransferase
       ```
   - All metadata tables will be merged with the main results table by the `gene` column

### Validating and Viewing the Configuration



After editing the `config.yml` file, you can use the `configuration.py` script to **validate and print the configuration**. This will help you ensure that everything is loaded correctly.

#### Steps:

1. **Run the Configuration Script:**
   - In your terminal, navigate to the repository directory and run the following command:
   ```bash
   python configuration.py --config_file config.yml
   ```

2. **Validation:**
   - The script will first validate that all the required keys are present in the `config.yml` file. If any required key is missing, an error will be raised.

3. **View the Loaded Configuration:**
   - After validation, the script will print the loaded configuration details, allowing you to verify that everything is set up correctly.


## Running the FastTarget Pipeline


Once you have downloaded the required databases and set up the configuration file, you can run the FastTarget pipeline using the `fasttarget.py` script.

### Steps:

1. **Run the FastTarget Script:**
   - In your terminal, navigate to the repository directory and run the following command:
   ```bash
   python fasttarget.py
   ```

   > **Tip:** If you want to run the pipeline with your own config file, use:
   ```bash
   python fasttarget.py --config_file my_config.yml
   ```

The results are stored in a file called `your_organism_name_results_table.tsv` in the folder of your organism.

### Understanding Output Columns

The output columns vary depending on your configuration:

**Core columns (always present):**
- `gene`: Locus_tag ID
- `uniprot`: UniProt identifier(s) for the protein

**Metabolism columns** (if metabolism analysis enabled):
- `betweenness_centrality`: Measure of the protein's centrality within the metabolic network
- `edges`: Number of edges connected to the protein in the network
- `chokepoints`: Whether the protein catalyzes a unique reaction (chokepoint)

**Structure columns** (if `structures.enabled: True`):

*Standard mode* (`pocket_full_mode: False`):
- `structure`: ID of the reference structure (PDB code, UniProt ID for AlphaFold, or ColabFold ID)
- `druggability_score`: Druggability score from FPocket for the best pocket in the reference structure
- `fpocket_pocket`: ID of the best FPocket-predicted pocket
- `p2rank_probability`: Probability score from P2Rank for the best pocket
- `p2rank_pocket`: ID of the best P2Rank-predicted pocket

*Full mode* (`pocket_full_mode: True`):
- `structure`: Set of all structure IDs available for this protein
- `best_fpocket_structure`: Structure containing the best FPocket pocket
- `druggability_score`: Druggability score from FPocket across all structures
- `fpocket_pocket`: ID of the best pocket found by FPocket
- `best_p2rank_structure`: Structure containing the best P2Rank pocket
- `p2rank_probability`: Best probability score from P2Rank across all structures
- `p2rank_pocket`: ID of the best pocket found by P2Rank

*ColabFold additional columns* (if `colabfold_run_all: True`):
- `colabfold_plddt`: Predicted Local Distance Difference Test score (model confidence)
- `colabfold_druggability_score`: FPocket druggability score for ColabFold model
- `colabfold_fpocket_pocket`: Best FPocket pocket in ColabFold model
- `colabfold_p2rank_probability`: P2Rank probability for ColabFold model
- `colabfold_p2rank_pocket`: Best P2Rank pocket in ColabFold model

**Conservation columns** (if `core.enabled: True`):
- `core_roary`: Whether the gene is in the core genome (Roary analysis)
- `core_corecruncher`: Whether the gene is in the core genome (CoreCruncher analysis)

**Offtarget columns** (if `offtarget.enabled: True`):
- `human_offtarget`: BLASTp hit in the human proteome (e-value and identity %)
- `gut_microbiome_offtarget`: Normalized score based on hits in the gut microbiome (0-1 scale, where 1 = ≥1000 hits)
- `foldseek_human_offtarget`: Structural similarity to human proteins (if `foldseek_human: True`)

**Essentiality columns** (if `deg.enabled: True`):
- `hit_in_deg`: BLASTp hit in the Database of Essential Genes (DEG)

**Localization columns** (if `psortb.enabled: True`):
- `psortb_localization`: Predicted subcellular localization

**Metadata columns** (if `metadata.enabled: True`):
- Additional columns from your metadata tables will be merged based on the `gene` column

## Running (Nextflow)

Nextflow is not bundled with FastTarget. Install Nextflow on your system before running the Nextflow pipeline. Tested with Nextflow v25.10.3.

## ⚡ **Running (Nextflow)**

The `nextflow/` directory provides a highly-parallel implementation. Typical usage (from within `nextflow/`):

```bash
cd nextflow
nextflow run main.nf --config_file ../config.yml
```

The Nextflow wrappers call the same Python functions in `ftscripts` and add parallelization, retry and HPC profile support. Use `-resume` to continue interrupted runs.


## Troubleshooting and tips


## 🛠️ **Troubleshooting and Tips**

- If a module repeatedly fails, check its module log under the organism folder and the `ftscripts/logger.py` outputs.
- For heavy I/O steps (structures/pockets) prefer Nextflow with `-profile docker`/`singularity` and tune `maxForks` in the Nextflow modules.
- Use `configuration.py` to catch configuration mistakes before running long jobs.


## Key files and components


## 📁 **Key Files and Components**

### Main Scripts
- `fasttarget.py` — main Python pipeline driver for standalone execution
- `configuration.py` — loads, validates, and prints `config.yml` configuration
- `databases.py` — manages database downloads

### Configuration Files
- `config.yml` — main configuration template (copy and edit for your project)
- `config_test.yml` — configuration for running the test case
- `requirements.yml` — conda environment specification

### Setup Scripts
- `setup_docker.sh` — pulls required Docker container images
- `setup_containers.sh` — pulls required Singularity/Apptainer container images (auto-detects which is available)
- `setup_singularity.sh` — legacy script, use setup_containers.sh instead

### Core Modules (`ftscripts/`)
Package containing all analysis implementations called by both `fasttarget.py` and Nextflow:
- `files.py` — file handling, I/O operations, JSON/dict utilities
- `genome.py` — genome processing, core genome analysis (Roary/CoreCruncher)
- `structures.py` — structure downloading, mapping, pocket prediction
- `pathways.py` — metabolic network analysis (Pathway Tools / SBML)
- `offtargets.py` — offtarget screening (human, microbiome, Foldseek)
- `essentiality.py` — DEG database analysis
- `metadata.py` — metadata table merging and processing
- `programs.py` — external program execution wrappers
- `logger.py` — logging configuration and utilities
- `build_human_pdb_index.py` — script to rebuild human PDB/AlphaFold index

### Data Directories
- `databases/` — downloaded database files and indexes (human proteome, DEG, microbiome catalogue)
- `organism/` — default output folder; each run creates a subfolder with results
- `singularity_sfi_files/` — cached Singularity container images

### Nextflow Implementation
- `nextflow/` — HPC/cluster parallelized implementation
  - `main.nf` — main Nextflow workflow orchestration
  - `nextflow.config` — Nextflow configuration and profiles
  - `modules/` — individual Nextflow process modules
  - `workflows/` — workflow composition and logic
  - `bin/` — helper scripts for Nextflow processes

### Documentation & Examples
- `README.md` — project overview and information
- `tutorial/` — additional tutorials (e.g., obtaining Pathway Tools files)
- `validate_test.py` — script to validate test case results


---

# TargetPathogenWeb

**TargetPathogenWeb** is a bioinformatic web server designed to identify molecular targets for novel drugs, facilitating the discovery and testing of new pharmaceutical compounds.

## Features
- **Target Identification:** Analyze molecular targets suitable for drug development.
- **User-Friendly Interface:** Web-based platform accessible from any browser.
- **Scalability:** Capable of handling large datasets efficiently.

## Requirements

To run TargetPathogenWeb, you need the following:

- **Operating System:** Linux
- **Docker:** [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose:** [Install Docker Compose](https://docs.docker.com/compose/install/)
- **SSH Key:** Ensure that your SSH key is loaded in your agent to access the Cluster of the Calculus Institute at the University of Buenos Aires.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sndg-arg/targetpathogenweb.git
   cd targetpathogenweb
   ```

2. **Run Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

3. **Access the web server:**      
   Open your browser and navigate to `http://localhost:8000`.

## Engineering Baseline

For day-to-day engineering work:

```bash
pip install -r requirements/dev.txt
make lint
make format
make test
make qa
```

## Health and Observability Endpoints

- `GET /health/live`
- `GET /health/ready`
- `GET /health/pipeline`

## Technical Docs

- `docs/ARCHITECTURE.md`
- `docs/ENGINEERING_QUALITY.md`
- `docs/OBSERVABILITY.md`
- `docs/UX_BIOINFO_PRODUCT.md`
- `docs/COLOR_SYSTEM.md`
- `COLOR_PALETTE.md`

## Usage

Local dev vs cluster deploy
- Dev/local: run `docker compose up -d --build` on your laptop; only InterProScan jumps to the UBA cluster via SSH (agent key `agutson`).
- Deploy on cluster: run the same `docker-compose.yml` on the cluster host (no Mac override). Mount the expected volumes and load the `target:conded` image. Everything else is identical.

### Pipeline explained for software engineers (beginner bio level)
If you come from software and have little biology background, this is the core idea:
- A **genome** is DNA text (letters `A/C/G/T`).
- A **gene** is a segment of that DNA.
- A **protein** is the translated product of a gene (amino-acid sequence).

Key file formats:
- `FASTA`: sequence format (`>header` + sequence lines).
- `.fna`: **nucleotide** FASTA (DNA).
- `.faa`: **amino-acid** FASTA (proteins).
- `.gbk`: GenBank file (sequence + annotations).
- `.gff`: genomic features with coordinates.
- `.tsv`: tab-separated result tables.
- `.pdb`: 3D protein structure file.

Quick pipeline summary:
1. Takes one genome (`.gbk`) and loads it.
2. Extracts/organizes genes and proteins (`.fna`, `.faa`, `.gff`).
3. Computes per-protein scores (offtarget, essentiality, etc.).
4. Runs InterProScan on proteins to detect conserved domains/regions.
5. Generates/loads 3D structures (AlphaFold) and pockets.
6. Links known ligands and exposes everything in the UI.

InterProScan in simple terms:
- Input: proteins (`.faa`).
- Process: matches each protein against known signatures (families, domains, motifs).
- Output: `.tsv` table with hits and `start/end` ranges on the protein sequence.
- Front: shown at `/protein/<id>` under `Annotations` and `Sequence Features`.

### Task-by-task map (actual order in `parsl/run_pipeline.py`)
Note: numeric Parsl task IDs (`Task 1`, `Task 2`, etc.) can vary between runs, but the execution order below is stable.

| Order | Task (code) | What it does | Main output(s) | Front section |
|---|---|---|---|---|
| 1 | `clear_folder` | Removes previous output folder for that genome run | clean run dir | no direct UI |
| 2 | `test_gbk` / `download_gbk` / `custom_gbk` | Gets genome input (`--test`, NCBI, or custom) | `*.gbk.gz` | no direct UI |
| 3 | `load_gbk` | Loads genome and proteins into DB | DB genome/proteome records | `/genomes`, `/assembly/<genome>/protein` |
| 4 | `fasttarget` (`fast_command`) | Runs FastTarget scoring pipeline | offtarget/essentiality TSVs | used by protein ranking/scores |
| 5 | `load_score(human_offtarget)` | Loads human offtarget score | score rows in DB | score-based filtering/ranking |
| 6 | `load_score(micro_offtarget)` | Loads microbiome offtarget score | score rows in DB | score-based filtering/ranking |
| 7 | `load_score(essenciality)` | Loads essentiality score | score rows in DB | score-based filtering/ranking |
| 8 | `index_genome_db` | Builds searchable DB indexes | search indexes | genome/protein navigation |
| 9 | `index_genome_seq` / `index_genome_seq_clean` | Writes indexed sequence files | `*.fna.gz`, `*.genes.fna.gz`, `*.faa.gz`, `*.gff.gz` | no direct UI |
| 10 | `interproscan` | Runs InterProScan remotely over protein sequences | `*.faa.tsv` | source for protein annotations |
| 11 | `load_interpro` | Loads InterPro domain hits into DB | feature/domain records | `/protein/<id>`: `Annotations`, `Sequence Features` |
| 12 | `gbk2uniprot_map` | Maps local locus tags to UniProt accessions | `*_unips.lst`, `*_unips_mapping.csv` | no direct UI |
| 13 | `get_unipslst` | Reads UniProt list to schedule structure tasks | in-memory uniprot list | no direct UI |
| 14 | `alphafold_unips` (N tasks) | Downloads/builds AlphaFold models (one task per mapped protein) | `*_af.pdb` files | basis for 3D protein view |
| 15 | `strucutures_af` | Loads AF structures and pocket predictions (Fpocket/P2Rank) | structures + pockets in DB | `/protein/<id>`: 3D viewer + `Pockets` |
| 16 | `druggability_2_csv` | Builds druggability table from pocket properties | `druggability.tsv` | score-based filtering/ranking |
| 17 | `load_score(druggability)` | Loads druggability score | score rows in DB | score-based filtering/ranking |
| 18 | `psort` | Predicts subcellular localization | psort output table | score-based filtering/ranking |
| 19 | `load_score(psort)` | Loads localization score | score rows in DB | score-based filtering/ranking |
| 20 | `get_binders` | Links proteins to known ligands (BioLiP/CCD) | `binders.csv` | basis for binder cards |
| 21 | `load_binders` | Loads binders into DB | binder rows in DB | `/protein/<id>`: `Binders` cards |

### Pipeline step-by-step (what each stage does, with files)
1. `clear_folder`
   - Cleans previous outputs for the genome run.
2. `test_gbk` / `download_gbk` / `custom_gbk`
   - Gets `.gbk.gz` input (test, NCBI, or custom file).
3. `load_gbk`
   - Loads genome/proteins into DB.
4. `fasttarget` (`fast_command`)
   - Computes score tables (`human_offtarget`, `micro_offtarget`, `essenciality`).
5. `load_score(...)` (x3)
   - Loads those scores into DB.
6. `index_genome_db`
   - Builds search indexes.
7. `index_genome_seq` / `index_genome_seq_clean`
   - Generates/indexes sequence files:
   - `*.fna.gz` (DNA), `*.genes.fna.gz` (gene nucleotides), `*.faa.gz` (proteins), `*.gff.gz` (features).
8. `interproscan`
   - Runs InterProScan over `*.faa.gz`.
   - Produces `*.faa.tsv` with domain/family/region hits.
9. `load_interpro`
   - Loads InterPro results into DB.
10. `gbk2uniprot_map` + `get_unipslst`
   - Maps local proteins to UniProt (`*_unips.lst`, `*_unips_mapping.csv`).
11. `alphafold_unips` (one task per mapped protein)
   - Generates `*_af.pdb` models.
12. `strucutures_af`
   - Loads structures + pockets (Fpocket/P2Rank) into DB.
13. `druggability_2_csv` + `load_score(druggability)`
   - Computes and loads druggability score.
14. `psort` + `load_score(psort)`
   - Predicts subcellular localization and loads it as score.
15. `get_binders` + `load_binders`
   - Builds `binders.csv` (known ligands) and loads it.

### **Important Warning:**
Before running the `run_pipeline` step, please shut down any processes that may be running, such as Firefox or Chrome, to avoid potential issues. The process can take up to some days depending on the size of the genome.

To add a new genome, first enter the web container. We recommend using [lazydocker](https://github.com/jesseduffield/lazydocker). Once inside the container, run the following commands:

1. **Activate the environment:**
   ```bash
   conda activate tpv2
   ```

2. **Move to the parsl folder and source the exports:**
   ```bash
   cd parsl
   source exports.sh
   ```

3. **(Needed the first time) Run the test command:**      
   ```bash
   python run_pipeline.py --test
   ```

4. **Load the new genome using the NCBI accession:**

   You should pass the NCBI accession at the end and declare if the organism is Gram-positive (`--gram p`) or Gram-negative (`--gram n`).   
   For example, to run the Gram-negative organism *Pseudomonas aeruginosa* PAO1, you should run:
   ```bash
   python run_pipeline.py --gram n NC_002516.2
   ```

5. **Load the new genome using a custom .gbk.gz file:**

   If instead of the official NCBI's genome you want to use a custom file corresponding to novel strains or with hand-made curations use the --custom to pass the custom gbk.gz file.
   ```bash
   python run_pipeline.py --gram n --custom NC_002516.2.gbk.gz
   ```

## License



## Contact


---

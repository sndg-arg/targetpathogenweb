
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
   docker build --no-cache -t target:conded . && docker compose up
   ```

3. **Access the web server:**      
   Open your browser and navigate to `http://localhost:8000`.

## Usage

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
   source export.sh
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

### **Important Warning:**
Before running the `run_pipeline` step, please shut down any processes that may be running, such as Firefox or Chrome, to avoid potential issues.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

For any inquiries, please reach out to us at [contact@yourdomain.com](mailto:contact@yourdomain.com).

---

Feel free to adjust any section according to your project's specifics!

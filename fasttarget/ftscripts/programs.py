import subprocess
import shlex
import docker
import os
import sys
import multiprocessing
from ftscripts import files
import SNDG
import json
import sys
import glob
import pwd
import grp
import time
from pathlib import Path
import shutil
import logging
import getpass

def _is_singularity_like_engine(container_engine):
    """
    Return True for engines that use Singularity-compatible .sif execution.
    """
    return str(container_engine).lower() in ('singularity', 'apptainer')


def change_permission_user_file(file_path):
    """
    Change the permissions of a file to the current user.
    
    :param file_path: The file path.
    """

    username = os.getenv('SUDO_USER') if os.getenv('SUDO_USER') else getpass.getuser()
    pw = pwd.getpwnam(username)
    uid = pw.pw_uid
    gid = pw.pw_gid

    try:
        os.chmod(file_path, 0o644)
        os.chown(file_path, uid, gid)
        print(f"Permissions changed for file {file_path}.")
    except Exception as e:
        logging.exception(f"Failed to change permissions for file {file_path}: {e}")

def change_permission_user_dir(directory_path):
    """
    Change the permissions of a directory and its contents to the current user.
    
    :param directory_path: The directory path.
    """
    
    username = os.getenv('SUDO_USER') if os.getenv('SUDO_USER') else getpass.getuser()
    pw = pwd.getpwnam(username)
    uid = pw.pw_uid
    gid = pw.pw_gid

    for root, dirs, files in os.walk(directory_path):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            try:
                os.chmod(dir_path, 0o755)
                os.chown(dir_path, uid, gid)
                #print(f"Permissions changed for directory {dir_path}.")
            except Exception as e:
                logging.exception(f"Failed to change permissions for directory {dir_path}: {e}")
        
        for file_name in files:
            file_path = os.path.join(root, file_name)
            try:
                os.chmod(file_path, 0o644)
                os.chown(file_path, uid, gid)
                #print(f"Permissions changed for file {file_path}.")
            except Exception as e:
                logging.exception(f"Failed to change permissions for file {file_path}: {e}")

def load_config(base_path):
    """
    Load the configuration 'config.json' file.

    :param base_path: Base path where the repository data is stored.
    """
    
    config_path = f'{base_path}/config.json'
    with config_path.open() as file:
        config = json.load(file)
    return config

def run_bash_command_with_retries(cmd_list, retries=3, delay=5):
    """
    Run a bash command with retry logic.

    :param cmd_list: List of command arguments [program, arg1, arg2, ...]
    :param retries: Number of retries if the command fails. Default is 3.
    :param delay: Delay (in seconds) between retries. Default is 5 seconds.
    """
    attempt = 0
    while attempt < retries:
        try:
            print(f'Running (attempt {attempt+1}/{retries}):', " ".join(repr(a) for a in cmd_list))
            result = subprocess.run(
                cmd_list,
                check=True,
                capture_output=True,
                text=True
            )
            print(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"STDERR:\n{result.stderr}")
            print("Command executed successfully.")
            return result.stdout

        except subprocess.CalledProcessError as e:
            print(f"Command failed with return code {e.returncode}.")
            print(f"STDERR:\n{e.stderr}")
            attempt += 1
            if attempt < retries:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print("Max retries reached. Command failed.")
                raise

    return None


def run_bash_command(cmd_list, capture_output=True):
    """
    Run a bash command.
    
    :param cmd_list: List of command arguments [program, arg1, arg2, ...]
    :param capture_output: Whether to capture stdout/stderr
    """
    try:
        print("Running:", " ".join(repr(a) for a in cmd_list))
        result = subprocess.run(
            cmd_list,  # List, not string
            check=True,  # Raises CalledProcessError on failure
            capture_output=capture_output,
            text=True
        )
        print(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            print(f"STDERR:\n{result.stderr}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Command failed with return code {e.returncode}")
        print(f"STDERR:\n{e.stderr}")
        raise


def run_docker_container(work_dir, bind_dir, image_name, command, env_vars=None, volumes=None):
    """
    Run a docker container.

    :param work_dir: Working directory path.
    :param bind_dir: Binding directory path in container.
    :param image_name: The image to run.
    :param command: The command to run.
    :param env_vars: Dictionary of environment variables to set in the container.
    :param volumes: Dictionary of volumes to mount in the container.

    """
    # Convert work_dir to absolute path for consistency
    work_dir = os.path.abspath(work_dir)
    
    # Convert bind_dir to absolute path if it's relative
    if not os.path.isabs(bind_dir):
        bind_dir = os.path.abspath(bind_dir)
    
    client = docker.from_env()

    if volumes == None:
        volumes = {work_dir: {'bind': bind_dir, 'mode': 'rw'}}
    else:
        # Ensure all volume paths are absolute
        abs_volumes = {}
        for host_path, mount_info in volumes.items():
            abs_host_path = os.path.abspath(host_path)
            container_path = mount_info['bind']
            # Ensure container path is absolute
            if not os.path.isabs(container_path):
                container_path = os.path.abspath(container_path)
            abs_volumes[abs_host_path] = {'bind': container_path, 'mode': mount_info.get('mode', 'rw')}
        volumes = abs_volumes
    
    user_str = f"{os.getuid()}:{os.getgid()}"

    try:
        print(f'Running docker image {image_name}, command: {command}')
        container = client.containers.run(
            image_name,
            command,
            volumes=volumes,
            working_dir= bind_dir,
            user=user_str,
            remove=True,
            stdout=True,
            stderr=True,
            environment=env_vars 
        )
        print(container.decode('utf-8'))
    except docker.errors.ContainerError as e:
        print(f"Error running container: {e}")
        raise  # Re-raise the exception so caller can handle it properly

def run_singularity_container(work_dir, bind_dir, image_name, command, env_vars=None, volumes=None, sif_dir='singularity_sfi_files'):
    """
    Run a singularity/apptainer container.
    Automatically detects whether to use apptainer or singularity.

    :param work_dir: Working directory path.
    :param bind_dir: Binding directory path in container.
    :param image_name: The Docker image name (will be converted to .sif filename).
    :param command: The command to run.
    :param env_vars: Dictionary of environment variables to set in the container.
    :param volumes: Dictionary of volumes to mount in the container.
    :param sif_dir: Directory where Singularity/Apptainer .sif files are stored.

    """
    # Detect whether to use apptainer or singularity
    container_cmd = 'apptainer' if shutil.which('apptainer') else 'singularity'
    
    # Convert work_dir to absolute path to avoid path duplication issues with bind mounts
    work_dir = os.path.abspath(work_dir)
    
    # Singularity/Apptainer requires both source and destination paths to be absolute
    if not os.path.isabs(bind_dir):
        bind_dir = os.path.abspath(bind_dir)
    
    # Build candidate .sif names from Docker image name
    # e.g., "fpocket/fpocket" -> "fpocket_fpocket.sif"
    # e.g., "mcpalumbo/p2rank:latest" -> "mcpalumbo_p2rank_latest.sif"
    image_no_tag = image_name.split(':', 1)[0]
    tag = image_name.split(':', 1)[1] if ':' in image_name else None
    sif_candidates = [image_name.replace('/', '_').replace(':', '_') + '.sif']

    # Also allow no-tag naming
    sif_candidates.append(image_no_tag.replace('/', '_') + '.sif')

    # If image includes registry prefix (e.g. ghcr.io/org/img:tag), also try without it
    image_parts = image_name.split('/')
    if len(image_parts) > 2 and ('.' in image_parts[0] or ':' in image_parts[0]):
        no_registry = '/'.join(image_parts[1:])
        sif_candidates.append(no_registry.replace('/', '_').replace(':', '_') + '.sif')

    # Get the base path (assuming sif_dir is relative to project root)
    if not os.path.isabs(sif_dir):
        module_dir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.dirname(module_dir)  # Go up from ftscripts/ to project root
        
        if not os.path.exists(os.path.join(base_path, 'fasttarget.py')):
            # Fallback: search upward from current working directory
            base_path = os.getcwd()
            while not os.path.exists(os.path.join(base_path, 'fasttarget.py')) and base_path != os.path.dirname(base_path):
                base_path = os.path.dirname(base_path)
        
        sif_base_dir = os.path.join(base_path, sif_dir)
    else:
        sif_base_dir = sif_dir

    # Resolve first existing candidate
    sif_path = None
    for sif_name in dict.fromkeys(sif_candidates):
        candidate = os.path.join(sif_base_dir, sif_name)
        if os.path.exists(candidate):
            sif_path = candidate
            break

    # Fallback: fuzzy match by repo name and optional tag
    if sif_path is None and os.path.isdir(sif_base_dir):
        repo_name = image_no_tag.split('/')[-1].lower()
        all_sifs = [f for f in os.listdir(sif_base_dir) if f.endswith('.sif')]
        repo_matches = [f for f in all_sifs if repo_name in f.lower()]
        if tag:
            tag_matches = [f for f in repo_matches if tag.lower() in f.lower()]
            if tag_matches:
                sif_path = os.path.join(sif_base_dir, sorted(tag_matches)[0])
        if sif_path is None and repo_matches:
            sif_path = os.path.join(sif_base_dir, sorted(repo_matches)[0])

    # Check if the .sif file exists
    if sif_path is None:
        expected = ", ".join(dict.fromkeys(sif_candidates))
        raise FileNotFoundError(
            f"Container image not found in {sif_base_dir}. "
            f"Tried: {expected}. Run setup_containers.sh first."
        )
    
    # Build bind mounts
    bind_mounts = []
    if volumes:
        for host_path, mount_info in volumes.items():
            # Convert host_path to absolute path to avoid path duplication
            abs_host_path = os.path.abspath(host_path)
            container_path = mount_info['bind']
            # Ensure container path is absolute for Singularity
            if not os.path.isabs(container_path):
                container_path = os.path.abspath(container_path)
            bind_mounts.append(f"{abs_host_path}:{container_path}")
    else:
        bind_mounts.append(f"{work_dir}:{bind_dir}")
    
    # Build container command using detected tool
    container_cmd_list = [container_cmd, 'exec']
    
    
    # Add isolation flags to prevent host environment contamination
    container_cmd_list.append('--contain')  # Maximum isolation
    container_cmd_list.append('--cleanenv')    # Don't inherit host environment variables  

    # Add bind mounts
    for bind in bind_mounts:
        container_cmd_list.extend(['--bind', bind])
    
    # Add environment variables
    if env_vars:
        for key, value in env_vars.items():
            container_cmd_list.extend(['--env', f'{key}={value}'])
    
    # Set working directory
    container_cmd_list.extend(['--pwd', bind_dir])
    
    # Add the .sif file
    container_cmd_list.append(sif_path)
    
    # Add the command (as a single string or split)
    if isinstance(command, str):
        container_cmd_list.extend(command.split())
    else:
        container_cmd_list.extend(command)
    
    try:
        print(f'Running {container_cmd} image {os.path.basename(sif_path)}, command: {command}')
        result = subprocess.run(
            container_cmd_list,
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout)
        if result.stderr:
            print(f"STDERR: {result.stderr}")
    except subprocess.CalledProcessError as e:
        print(f"Error running {container_cmd} container: {e}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise

def run_container(work_dir, bind_dir, image_name, command, env_vars=None, volumes=None, container_engine='docker'):
    """
    Run a container using either Docker or Singularity based on configuration.

    :param work_dir: Working directory path.
    :param bind_dir: Binding directory path in container.
    :param image_name: The image to run.
    :param command: The command to run.
    :param env_vars: Dictionary of environment variables to set in the container.
    :param volumes: Dictionary of volumes to mount in the container.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """
    if _is_singularity_like_engine(container_engine):
        return run_singularity_container(work_dir, bind_dir, image_name, command, env_vars, volumes)
    elif container_engine.lower() == 'docker':
        return run_docker_container(work_dir, bind_dir, image_name, command, env_vars, volumes)
    else:
        raise ValueError(f"Unknown container engine: {container_engine}. Use 'docker', 'singularity', or 'apptainer'.")


def run_fpocket(work_dir, pdb_file, container_engine='docker'):

    """
    Run FPocket, using the container image 'fpocket/fpocket'.
    
    :param work_dir:  Working directory path.
    :param pdb_file:  Structure file (.pdb) path.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """

    if os.path.exists(pdb_file):
        # Convert to relative path from work_dir for Singularity compatibility
        work_dir_abs = os.path.abspath(work_dir)
        pdb_file_rel = os.path.relpath(pdb_file, work_dir_abs)
        
        FPOCKET_image = "fpocket/fpocket"
        FPOCKET_command = ["fpocket", "-f", pdb_file_rel]

        run_container(work_dir, work_dir, FPOCKET_image, FPOCKET_command, container_engine=container_engine)

        # rename output folder
        pdb_basename = os.path.basename(os.path.splitext(pdb_file)[0])
        original_outdir = os.path.join(work_dir, pdb_basename + "_out")
        new_outdir = os.path.join(work_dir, pdb_basename + "_fpocket")
        if os.path.exists(original_outdir):
            os.rename(original_outdir, new_outdir)
    else:
        logging.error(f"The file '{pdb_file}' not found.")

def run_p2rank(work_dir, pdb_file, cpus, alphafold=False, container_engine='docker'):
    """
    Run P2Rank inside the container image 'mcpalumbo/p2rank:latest'.
    Creates a folder for each pdb file with '_p2rank' suffix in work_dir.

    :param work_dir:  Working directory path (mounted inside the container).
    :param pdb_file:  Structure file (.pdb) path.
    :param cpus: Number of threads (CPUs) to use. 
    :param alphafold: Boolean, if True adds '-c alphafold' to the command.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """

    #create output directory if not exists for my pdb
    pdb_basename = os.path.basename(os.path.splitext(pdb_file)[0])+"_p2rank"
    pdb_output_dir = os.path.join(work_dir, pdb_basename)

    if not os.path.exists(pdb_output_dir):
        os.makedirs(pdb_output_dir, exist_ok=True)

    if os.path.exists(pdb_file):
        # Convert to relative paths from work_dir for Singularity compatibility
        work_dir_abs = os.path.abspath(work_dir)
        pdb_file_rel = os.path.relpath(pdb_file, work_dir_abs)
        pdb_output_dir_rel = os.path.relpath(pdb_output_dir, work_dir_abs)
        
        P2RANK_image = "mcpalumbo/p2rank:latest"
        P2RANK_command = ["prank", "predict", "-f", pdb_file_rel, "-o", pdb_output_dir_rel, "-threads", str(cpus)]
        if alphafold:
            P2RANK_command.extend(["-c", "alphafold"])

        run_container(work_dir, work_dir, P2RANK_image, P2RANK_command, container_engine=container_engine)
    else:
        print(f"The file '{pdb_file}' not found.")
        raise FileNotFoundError(f'{pdb_file} not found.')

def run_colabfold_batch(input_fasta, output_dir, amber=False, gpu_relax=False):
    """
    Run ColabFold batch script.
    :param input_fasta: Input fasta file path.
    :param output_dir: Output directory path.
    :param amber: Whether to use AMBER for relaxation. Default False.
    :param gpu_relax: Run amber on GPU. Default False.
    """

    if files.file_check(input_fasta):
        colabfold_command = [
            'colabfold_batch',
            input_fasta,
            output_dir
        ]
        if amber:
            colabfold_command.extend(['--amber', '--num-models', '3', '--num-relax', '1'])
        if gpu_relax:
            colabfold_command.append('--use-gpu-relax')
        
        run_bash_command(colabfold_command)
    else:
        logging.error(f"Input fasta file '{input_fasta}' not found.")  

def run_metagraphtools(work_dir, model_file, filter_file=None, chokepoints=True, graph=True, container_engine='docker'):
    
    """
    Run MetaGraphTools inside the container image 'mcpalumbo/metagraphtools:latest'.
    Generates a folder MGT_results_<date> in the working directory.
    
    :param work_dir: Working directory where the data is located and results will be saved.
    :param model_file: Path to the SBML model file.
    :param filter_file: Path to the frequency filter file (TSV format). If no file provided, uses metabolites with a frequency higher than 20 in the model.
    :param chokepoints: Whether to calculate chokepoints. Default True.
    :param graph: Whether to generate graphs. Default True.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.
    """
    
    # Ensure work_dir is absolute path
    work_dir = os.path.abspath(work_dir)
    bind_dir = '/data'
    image_name = 'mcpalumbo/metagraphtools:latest'
    
    # Build the MetaGraphTools command arguments
    mgt_command = [
        'MetaGraphTools',
        '--model',
        f'/data/{os.path.basename(model_file)}'
    ]
    
    # Add optional flags
    if chokepoints:
        mgt_command.append('--chokepoints')
    if graph:
        mgt_command.append('--graph')
    
    # Add frequency filter file if provided
    if filter_file:
        mgt_command.extend(['--frequency_filter_file', f'/data/{os.path.basename(filter_file)}'])
    
    # Set environment variable for HOME (needed for cache directories)
    env_vars = {'HOME': '/tmp'}
    
    try:
        run_container(
            work_dir=work_dir,
            bind_dir=bind_dir,
            image_name=image_name,
            command=mgt_command,
            env_vars=env_vars,
            container_engine=container_engine
        )
        print('MetaGraphTools completed successfully.')

    except Exception as e:
        logging.exception(f'Error running MetaGraphTools: {e}')
        raise


def run_cd_hit(input_fasta, output_fasta, identity=1.0, aln_coverage_short=0.9, aln_coverage_long=0.9, use_global_seq_identity=True, accurate_mode=True, cpus=multiprocessing.cpu_count()):

    """
    Runs CD-HIT command line.
    
    :param input_fasta: Input fasta file path.
    :param output_fasta: Output fasta file path.
    :param identity: Sequence identity threshold. Default 1.0 (100% of identical residues).
    :param aln_coverage_short: Alignment coverage for the shorter sequence. Default 0.9.
    :param aln_coverage_long: Alignment coverage for the longer sequence. Default 0.9.
    :param use_global_seq_identity: Use global sequence identity. Default True.
    :param accurate_mode: Use accurate mode. Default True.
    :param cpus: Number of threads (CPUs) to use in cd-hit.
    
    """
    if files.file_check(input_fasta):

        cd_hit_command = [
            'cd-hit',
            '-i', input_fasta,
            '-o', output_fasta,
            '-c', str(identity),
            '-aS', str(aln_coverage_short),
            '-aL', str(aln_coverage_long),
            '-G', '1' if use_global_seq_identity else '0',
            '-g', '1' if accurate_mode else '0',
            '-T', str(cpus)
        ]
        run_bash_command(cd_hit_command)
    else:
        logging.error(f"Input fasta file '{input_fasta}' not found.")

def run_blastp(blastdb, query, output, evalue='1e-5', max_hsps='1', outfmt='6', max_target_seqs='500',cpus=multiprocessing.cpu_count()):

    """
    Runs Protein-Protein BLAST command line.
    
    :param blastdb: BLAST database name (full path).
    :param query: Query fasta (protein) file path.
    :param output: Output file path.
    :param evalue: Expect value (E) for saving hits. Default 1e-5.
    :param max_hsps: Maximum number of HSPs (alignments) to keep for any single query-subject pair. Default 1.
    :param outfmt: Output format. Default 6 (tabular).
    :param max_target_seqs: Number of aligned sequences to keep.
    :param cpus: Number of threads (CPUs) to use in blast search.
    
    """
    if files.file_check(query):

        blastp_command = [
            'blastp',
            '-evalue', str(evalue),
            '-max_hsps', str(max_hsps),
            '-outfmt', str(outfmt),
            '-db', blastdb,
            '-query', query,
            '-num_threads', str(cpus),
            '-max_target_seqs', str(max_target_seqs),
            '-out', output
        ]
        run_bash_command(blastp_command)
    else:
        logging.error(f"Query file '{query}' not found.")

def run_makeblastdb(input, output, title, dbtype, taxid=None):

    """
    Creates a BLAST database from command line.
    
    :param input: Input fasta file path.
    :param output: Output file path.
    :param title: Name of database.
    :param dbtype:  Molecule type of target db. Values: 'nucl' or 'prot'.
    :param taxid: Taxonomy ID for the database.
        
    """
    
    if files.file_check(input):
            makeblast_command = [
                'makeblastdb',
                '-in', input,
                '-title', title,
                '-out', output,
                '-parse_seqids',
                '-dbtype', dbtype
            ]
            if taxid is not None:
                makeblast_command.extend(['-taxid', str(taxid)])
            run_bash_command(makeblast_command)
    else:
        logging.error(f"Blast database file '{input}' not found.")


def run_diamond_blastp(blastdb, query, output, evalue='1e-5', max_hsps='1', outfmt='6',cpus=multiprocessing.cpu_count()):

    """
    Runs Protein-Protein Diamond BLAST command line.
    
    :param blastdb: Diamond BLAST database name (full path).
    :param query: Query fasta (protein) file path.
    :param output: Output file path.
    :param evalue: Expect value (E) for saving hits. Default 1e-5.
    :param max_hsps: Maximum number of HSPs (alignments) to keep for any single query-subject pair. Default 1.
    :param outfmt: Output format. Default 6 (tabular).
    :param cpus: Number of threads (CPUs) to use in blast search.
    
    """
    if files.file_check(query):

        diamond_blastp_command = [
            'diamond', 'blastp',
            '--evalue', str(evalue),
            '--max-hsps', str(max_hsps),
        ]
        
        # Handle outfmt: split if it contains spaces (e.g., "6 qseqid sseqid...")
        outfmt_parts = str(outfmt).split()
        if outfmt_parts:
            diamond_blastp_command.append('--outfmt')
            diamond_blastp_command.extend(outfmt_parts)
        
        diamond_blastp_command.extend([
            '--db', blastdb,
            '--query', query,
            '--threads', str(cpus),
            '--out', output
        ])
        
        run_bash_command(diamond_blastp_command)
    else:
        logging.error(f"Query file '{query}' not found.")


def run_makediamonddb(input, output):

    """
    Creates a Diamond BLAST database from command line.
    
    :param input: Input fasta file path.
    :param output: Output file path.
        
    """
    
    if files.file_check(input):
            makediamond_command = ['diamond', 'makedb', '--in', input, '--db', output]
            run_bash_command(makediamond_command)
    else:
        logging.error(f"Diamond Blast database file '{input}' not found.")


def run_genbank2gff3(input, output, container_engine='docker'):

    """
    Runs script bp_genbank2gff3.pl from BioPerl.
    Convert a GenBank file to a gff3 for Roary.

    :param input: Input gbk file path.
    :param output: Output directory path.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.
        
    """
    work_dir = os.path.dirname(input)
    bind_dir = '/data'
    image_name = 'mcpalumbo/bioperl:1'
    command = f'bp_genbank2gff3 /data/{os.path.basename(input)}'

    if not files.file_check(input):
        logging.error(f"GenBank file '{input}' not found.")
        raise FileNotFoundError(f"GenBank file '{input}' not found.")

    try:
        run_container(
            work_dir=work_dir,
            bind_dir=bind_dir,
            image_name=image_name,
            command=command,
            container_engine=container_engine
        )

        file_output = f'{input}.gff'
        file_final_name = os.path.splitext(input)[0] + '.gff'
        file_roary_name = os.path.basename(input).replace('.gbk', '.gff')
        file_final_roary = os.path.join(output, file_roary_name)

        if not os.path.exists(output):
            os.makedirs(output, exist_ok=True)

        if not os.path.exists(file_output):
            raise FileNotFoundError(
                f"bp_genbank2gff3 completed but did not create expected file '{file_output}'."
            )

        print('bp_genbank2gff3.pl executed successfully.')
        shutil.move(file_output, file_final_name)

        if not os.path.exists(file_final_roary):
            shutil.copy(file_final_name, file_final_roary)
            print(f'Gff3 file saved in {output}')

    except Exception as e:
        logging.exception(f'Error running bp_genbank2gff3.pl: {e}')
        raise

def run_roary(work_dir, input, output, core_threshold=99, identity=95, cluster_number=50000,cpus=multiprocessing.cpu_count(), container_engine='docker'):

    """
    Runs the docker image sangerpathogens/roary, a pan genome pipeline. Default options.
    More info: https://sanger-pathogens.github.io/Roary/

    :param work_dir: Directory where gff and roary output folders are.
    :param input: Directory where gff3 files are found.
    :param output: Output directory path.
    :param core_threshold: Threshold (in percentage) of isolates required to define a core gene.
    :param identity: Minimum percentage identity for sequence comparisons performed by blastp. 
    :param cpus: Number of threads.
    :param cluster_number: Cluster sequences. Default 50000.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """

    if os.path.exists(input):

        # Use glob to list .gff files safely
        
        gff_files = glob.glob(os.path.join(input, '*.gff'))
        if not gff_files:
            raise Exception(f"No .gff files found in {input}")

        # Convert absolute paths to relative paths from work_dir
        # This is necessary for Singularity/Apptainer containers
        work_dir_abs = os.path.abspath(work_dir)
        output_rel = os.path.relpath(output, work_dir_abs)
        gff_files_rel = [os.path.relpath(gff, work_dir_abs) for gff in gff_files]

        ROARY_image = "sangerpathogens/roary"
        ROARY_command = [
            "roary",
            "-p", str(cpus),
            "-g", str(cluster_number),
            "-cd", str(core_threshold),
            "-i", str(identity),
            "-f", output_rel
        ] + gff_files_rel

        run_container(work_dir, work_dir, ROARY_image, ROARY_command, container_engine=container_engine)
    else:
        logging.error(f"Directory '{input}' not found.")

def run_core_cruncher(corecruncher_dir, reference, core_threshold=99, identity=95, container_engine='docker'):
    """
    Runs CoreCruncher, a core genome tool. Default options.
    Runs the docker image mcpalumbo/corecruncher:1.
    More info: https://github.com/lbobay/CoreCruncher

    :param corecruncher_dir: Folder containing the input directory and where to find all the results of the analysis. faa/ subfolder must contain the genomes to analyze (.faa files).
    :param reference: Pivot genome, specify the name of the file.
    :param core_threshold: Minimum frequency of the gene across genomes to be considered core.
    :param identity: Identity score used by usearch or blast to define orthologs (percentage).
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """
   
    if os.path.exists(corecruncher_dir):
        if os.path.exists(os.path.join(corecruncher_dir, 'faa')):
            work_dir = corecruncher_dir
            bind_dir = '/data'
            image_name = 'mcpalumbo/corecruncher:1'
            command = [
                '/CoreCruncher/corecruncher_master.py',
                '-in', 'faa/',
                '-out', '/data',
                '-freq', str(core_threshold),
                '-score', str(identity),
                '-ref', reference
            ]  
            try:
                run_container(
                    work_dir=work_dir,
                    bind_dir=bind_dir,
                    image_name=image_name,
                    command=command,
                    container_engine=container_engine
                )
            except Exception as e:
                logging.exception(f'Error running corecruncher: {e}')
        else:
            logging.error(f"Directory '{os.path.join(corecruncher_dir, 'faa')}' not found.")
    else:
        logging.error(f"Directory '{corecruncher_dir}' not found.")

def run_foldseek_create_index_db(structures_dir, DB_name, container_engine='docker'):

    """
    Creates a database and indexes it for Foldseek, a tool designed for efficient protein structure comparison.
    Runs the docker image mcpalumbo/foldseek:1.
    More info: https://github.com/steineggerlab/foldseek

    :param structures_dir: Folder containing the .pdb structures to make the database.
    :param DB_name: Name of the database to create.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.
    
    """

    if os.path.exists(structures_dir):
        
        DB_foldseek_path = os.path.join(structures_dir, 'DB_foldseek')
        
        if not os.path.exists(DB_foldseek_path):
            os.makedirs(DB_foldseek_path, exist_ok=True)

        work_dir = structures_dir
        bind_dir = '/data'
        image_name = 'mcpalumbo/foldseek:1'
        
        # Singularity needs explicit entrypoint call (Docker uses ENTRYPOINT automatically)
        if _is_singularity_like_engine(container_engine):
            command_create = ["/usr/local/bin/entrypoint", "createdb", "/data", f"/data/DB_foldseek/{DB_name}"]
            command_index = ["/usr/local/bin/entrypoint", "createindex", f"/data/DB_foldseek/{DB_name}", "/data/DB_foldseek/tmp"]
            env_vars = {'PATH': '/usr/local/bin:/usr/bin:/bin'}
        else:
            command_create = ["createdb", "/data", f"/data/DB_foldseek/{DB_name}"]
            command_index = ["createindex", f"/data/DB_foldseek/{DB_name}", "/data/DB_foldseek/tmp"]
            env_vars = None

        try:
            run_container(
                work_dir=work_dir,
                bind_dir=bind_dir,
                image_name=image_name,
                command=command_create,
                container_engine=container_engine,
                env_vars=env_vars
            )
            try:
                run_container(
                    work_dir=work_dir,
                    bind_dir=bind_dir,
                    image_name=image_name,
                    command=command_index,
                    container_engine=container_engine,
                    env_vars=env_vars
                )
            except Exception as e:
                logging.exception(f'Error running foldseek createindex: {e}')
        except Exception as e:
            logging.exception(f'Error running foldseek createdb: {e}')
    else:
        logging.error(f"Directory '{structures_dir}' not found.")

def run_foldseek_search(structures_dir, DB_dir, DB_name, query, output_dir, container_engine='docker'):

    """
    Runs Foldseek easy-search, a tool designed for efficient protein structure comparison.
    Runs the docker image mcpalumbo/foldseek:1.
    More info: https://github.com/steineggerlab/foldseek

    :param structures_dir: Folder containing the .pdb structures to search in the database.
    :param DB_dir: Folder containing the database.
    :param DB_name: Name of the database.
    :param query: Query structure file name. Should be in structures_dir.
    :param output_dir: Output directory path.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.

    """
  
    if os.path.exists(structures_dir) and os.path.exists(output_dir):

        query_basename = query.split('.')[0]

        foldseek_results_tmp = os.path.join(structures_dir, f'{query_basename}_output_foldseek')
        foldseek_results_final = os.path.join(output_dir, f'{query_basename}_output_foldseek')
        results_tsv_file = os.path.join(foldseek_results_final, f'{query_basename}_vs_{DB_name}_foldseek_results.tsv')

        if os.path.exists(foldseek_results_tmp):
            shutil.rmtree(foldseek_results_tmp)

        if not os.path.exists(foldseek_results_final) or not files.file_check(results_tsv_file):
            if os.path.exists(DB_dir):

                if not os.path.exists(foldseek_results_tmp):
                    os.makedirs(foldseek_results_tmp, exist_ok=True)

                volumes = {
                    DB_dir: {'bind': '/data', 'mode': 'rw'},
                    structures_dir: {'bind': '/media', 'mode': 'rw'}
                    }
                work_dir = structures_dir
                bind_dir = '/media'
                image_name = 'mcpalumbo/foldseek:1'
                
                # Singularity needs explicit entrypoint call (Docker uses ENTRYPOINT automatically)
                # Create unique temp directory for this Foldseek run to avoid conflicts
                import uuid
                unique_tmp = f"/data/tmp_{uuid.uuid4().hex[:8]}"
                
                if _is_singularity_like_engine(container_engine):
                    command = [
                        "/usr/local/bin/entrypoint",
                        "easy-search",
                        f"/media/{query}",
                        f"/data/{DB_name}",
                        f"/media/{query_basename}_output_foldseek/{query_basename}_vs_{DB_name}_foldseek_results.tsv",
                        unique_tmp,
                        "--exhaustive-search", "1",
                        "--format-mode", "4",
                        "--format-output", "query,target,evalue,gapopen,pident,fident,nident,qstart,qend,qlen,tstart,tend,tlen,alnlen,mismatch,qcov,tcov,lddt,qtmscore,ttmscore,alntmscore,rmsd,prob"
                    ]
                    env_vars = {'PATH': '/usr/local/bin:/usr/bin:/bin'}
                else:
                    command = [
                        "easy-search",
                        f"/media/{query}",
                        f"/data/{DB_name}",
                        f"/media/{query_basename}_output_foldseek/{query_basename}_vs_{DB_name}_foldseek_results.tsv",
                        unique_tmp,
                        "--exhaustive-search", "1",
                        "--format-mode", "4",
                        "--format-output", "query,target,evalue,gapopen,pident,fident,nident,qstart,qend,qlen,tstart,tend,tlen,alnlen,mismatch,qcov,tcov,lddt,qtmscore,ttmscore,alntmscore,rmsd,prob"
                    ]
                    env_vars = None

                try:
                    run_container(
                        volumes=volumes,
                        work_dir=work_dir,
                        bind_dir=bind_dir,
                        image_name=image_name,
                        command=command,
                        env_vars=env_vars,
                        container_engine=container_engine
                    )

                    if os.path.exists(foldseek_results_final):
                        shutil.rmtree(foldseek_results_final)
                    # Move foldseek_results_tmp to output directory
                    shutil.move(foldseek_results_tmp, output_dir)
                    
                except Exception as e:
                    logging.exception(f'Error running foldseek easy-search: {e}')
            else:
                logging.error(f"Directory '{DB_dir}' not found. Please make the DB again.")
        else:
            logging.info(f"Foldseek results file '{results_tsv_file}' already exists.")
    else:
        logging.error(f"Directory '{structures_dir}' not found.")

 
def run_panx(panx_script, input, species_name, cpus=multiprocessing.cpu_count()):
    """
    Runs pan-genome-analysis, a pan-genome tool. Default options.
    More info: https://github.com/neherlab/pan-genome-analysis

    :param panx_script: Path of panX.py script.
    :param input: Path to a folder containing the genomes to analyze. It is the run directory.
    :param species_name: specie name. Used as prefix for some temporary folders (e.g.: P_aeruginosa).
    :param cpus: Number of threads.
    
    """
   
    if os.path.exists(panx_script):
        if os.path.exists(input):            
            panx_command = [panx_script, '-fn', f'{input}/', '-sl', species_name, '-t', str(cpus)]
            run_bash_command(panx_command)

        else:
            logging.error(f"Directory '{input}' not found.")
    else:
        logging.error(f"Script '{panx_script}' not found.")

def run_unzip(input_file, output_dir):
    
    """
    Unzip a file in a directory.
    
    :param input_file: File to unzip.
    :param output_dir: Directory where to unzip the file.
    """

    if os.path.exists(input_file):
        if os.path.exists(output_dir):            
            unzip_command = ['unzip', input_file, '-d', output_dir]
            run_bash_command(unzip_command)
            print(f'Unzip {input_file} in {output_dir}')
        else:
            logging.error(f"Directory '{output_dir}' not found.")
    else:
        logging.error(f"File '{input_file}' not found.")

def run_ncbi_datasets(tax_id, organism_name, output_dir):

    """
    Downloads genomes from ncbi for any taxonomy ID, in gbff format.
    Assembly level complete and annotated by RefSeq.
    More info: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/

    :param tax_id: Taxonomy ID (eg. Pseudomonas aeruginosa taxonomy ID: 287).
    :param output_dir: Output directory path.
    :param organism_name: Name given to directories to download (eg. PAO).
    
    """

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    dehydrated_file =  os.path.join(output_dir, f'{organism_name}_dehydrated.zip')
    dehydrated_dir =  os.path.join(output_dir, f'{organism_name}_dataset')
    checkpoint_file =  os.path.join(output_dir, f'{organism_name}_checkpoint_ncbi_datasets.txt')

    if not files.file_check(checkpoint_file):
        if not os.path.exists(dehydrated_file):
            datasets_command = [
                'datasets', 'download', 'genome', 'taxon', str(tax_id),
                '--assembly-level', 'complete',
                '--annotated',
                '--assembly-source', 'RefSeq',
                '--include', 'gbff,gff3',
                '--exclude-atypical',
                '--dehydrated',
                '--filename', dehydrated_file
            ]
            run_bash_command(datasets_command)
            print(f'Download a dehydrated data package in {dehydrated_file}')
        else:
            print(f'Dehydrated data package in {dehydrated_file}')
        
        if not os.path.exists(dehydrated_dir):
            os.makedirs(dehydrated_dir)
            print(f"Created directory: {dehydrated_dir}")
            run_unzip(dehydrated_file, dehydrated_dir)
            print(f'Unzip a dehydrated data package in {dehydrated_dir}')
        else:
            print(f'Dehydrated data package in {dehydrated_dir}')
        
        rehydrate_command = ['datasets', 'rehydrate', '--directory', dehydrated_dir]
        run_bash_command_with_retries(rehydrate_command)
        print(f'Rehydrated complete')
        
        print('NCBI download complete')

        with open(checkpoint_file, 'w') as f:
            f.write("Download complete: " + str(dehydrated_dir))
            f.close()
    else:
        logging.info(f"Checkpoint file '{checkpoint_file}' already exists.")
        logging.info(f"NCBI datasets download already completed.")

def run_ncbi_accession(accession, output_dir):

    """
    Downloads genomes from ncbi for any accession ID in gbff format.
    More info: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/

    :param accession: Accession ID.
    :param output_dir: Output directory path.
    
    """

    if os.path.exists(output_dir):

        file_download = os.path.join(output_dir, f'{accession}.zip')

        datasets_command = ['datasets', 'download', 'genome', 'accession', accession, '--include', 'gbff,gff3', '--filename', file_download]
        run_bash_command(datasets_command)
        run_unzip(file_download, output_dir)
        
        # Remove downloaded zip and README
        readme_path = os.path.join(output_dir, 'README.md')
        if os.path.exists(file_download):
            os.remove(file_download)
        if os.path.exists(readme_path):
            os.remove(readme_path)

        old_accesion_dir = os.path.join(output_dir, accession)
        if os.path.exists(old_accesion_dir):
            shutil.rmtree(old_accesion_dir)

        # Move accession data to output_dir
        src_path = os.path.join(output_dir, 'ncbi_dataset', 'data', accession)
        if os.path.exists(src_path):
            shutil.move(src_path, output_dir)
        
        # Remove ncbi_dataset directory
        ncbi_dataset_dir = os.path.join(output_dir, 'ncbi_dataset')
        if os.path.exists(ncbi_dataset_dir):
            shutil.rmtree(ncbi_dataset_dir)

    else:
        logging.error(f"Directory '{output_dir}' not found.")
    
    print(f'NCBI {accession} download complete in {output_dir }')

def run_ncbi_datasets_accessions(accession_list, organism_name, output_dir):
    """
    Downloads specific genomes from NCBI by accession list, in gbff format.
    More info: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/download-and-install/

    :param accession_list: List of NCBI assembly accessions (e.g., ['GCF_000006945.2', 'GCF_000027345.1']).
    :param organism_name: Name given to directories to download (eg. PAO).
    :param output_dir: Output directory path.
    """

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    dehydrated_file = os.path.join(output_dir, f'{organism_name}_dehydrated.zip')
    dehydrated_dir = os.path.join(output_dir, f'{organism_name}_dataset')
    checkpoint_file = os.path.join(output_dir, f'{organism_name}_checkpoint_ncbi_datasets.txt')

    if not files.file_check(checkpoint_file):
        if not os.path.exists(dehydrated_file):
            # Build command with all accessions
            datasets_command = [
                'datasets', 'download', 'genome', 'accession'
            ]
            # Add all accessions
            datasets_command.extend(accession_list)
            # Add remaining parameters
            datasets_command.extend([
                '--include', 'gbff,gff3',
                '--exclude-atypical',
                '--dehydrated',
                '--filename', dehydrated_file
            ])
            
            print(f'Downloading {len(accession_list)} genomes from accession list')
            run_bash_command(datasets_command)
            print(f'Download a dehydrated data package in {dehydrated_file}')
        else:
            print(f'Dehydrated data package in {dehydrated_file}')
        
        if not os.path.exists(dehydrated_dir):
            os.makedirs(dehydrated_dir)
            print(f"Created directory: {dehydrated_dir}")
            run_unzip(dehydrated_file, dehydrated_dir)
            print(f'Unzip a dehydrated data package in {dehydrated_dir}')
        else:
            print(f'Dehydrated data package in {dehydrated_dir}')
        
        rehydrate_command = ['datasets', 'rehydrate', '--directory', dehydrated_dir]
        run_bash_command_with_retries(rehydrate_command)
        print(f'Rehydrated complete')
        
        print('NCBI accession list download complete')

        with open(checkpoint_file, 'w') as f:
            f.write(f"Download complete from accession list: {len(accession_list)} genomes\n")
            f.write("Accessions:\n")
            for acc in accession_list:
                f.write(f"  - {acc}\n")
            f.close()
    else:
        logging.info(f"Checkpoint file '{checkpoint_file}' already exists.")
        logging.info(f"NCBI datasets download from accession list already completed.")

def run_ubiquitous(sbml_file, out_dir):
    
    """
    Generate a file with the ubiquitous compounds from a SBML file.
    
    :param sbml_file: SBML file path.
    :param out_dir: Output directory path.
    """
    
    if os.path.exists(sbml_file):
        if os.path.exists(out_dir):
            try:
                ubiquitous_command = ['python3', '-m', 'SNDG.Network.SBMLProcessor', '-i', sbml_file, '-o', f'{out_dir}/']
                run_bash_command(ubiquitous_command)
                print(f'Ubiquitous compounds file generated.')
            except Exception as e:
                logging.exception(f"Error generating ubiquitous compounds file: {e}")
        else:
            logging.error(f"Directory '{out_dir}' not found.")
    else:
        logging.error(f"SBML file '{sbml_file}' not found.")
  
def run_sbml_to_sif(sbml_file, ubiquitous_file, out_dir):
    
    """
    Generate a SIF file from a SBML file.
    
    :param sbml_file: SBML file path.
    :param ubiquitous_file: Ubiquitous compounds file path.
    :param out_dir: Output directory path.
    """

    if os.path.exists(sbml_file):
        if os.path.exists(ubiquitous_file):
            if os.path.exists(out_dir):
                try:
                    sif_command = ['python3', '-m', 'SNDG.Network.SBMLProcessor', '-i', sbml_file, '-o', f'{out_dir}/', '-f', ubiquitous_file]
                    run_bash_command(sif_command)
                    print(f'Sif file generated.')
                except Exception as e:
                    logging.exception(f"Error generating SIF file: {e}")
            else:
                logging.error(f"Directory '{out_dir}' not found.")
        else:
            logging.error(f"Ubiquitous compounds file '{ubiquitous_file}' not found.")
    else:
        logging.error(f"SBML file '{sbml_file}' not found.") 

def run_psort(input, organism_type, output_dir, output_format='terse', container_engine='docker'):
    """
    Runs PSORTb, a tool for predicting subcellular localization for a given set of protein sequences.
    More info: https://hub.docker.com/r/brinkmanlab/psortb_commandline

    :param input: Path to fasta file with protein sequences.
    :param organism_type: Type of organism, it can be Gram negative/positive bacteria or archaea. Only can take these values: n, p or a.
    :param output_dir:  Path of where to save results files.
    :param output_format: Format of output files. Value can be normal, terse or long. Default:terse.
    :param container_engine: 'docker' or 'singularity'. Default is 'docker'.
    
    """

    valid_type = ['a','n','p']
    if organism_type not in valid_type:
        raise ValueError("output_dir must be one of %r." % valid_type)

    valid_format = ['normal','terse','long']
    if output_format not in valid_format:
        raise ValueError("output_format must be one of %r." % valid_format)   
   
    if os.path.exists(input):
        if os.path.exists(output_dir):          

            shutil.copy(input, output_dir)

            # Create results subdirectory in output_dir (needed for Singularity)
            results_dir = os.path.join(output_dir, 'results')
            os.makedirs(results_dir, exist_ok=True)

            file_name = os.path.basename(input)

            image_name = 'brinkmanlab/psortb_commandline:1.0.2'
            psortb_command = f'/usr/local/psortb/bin/psort -{organism_type} -o {output_format} -i /tmp/{file_name}'

            env_vars = {'MOUNT': output_dir}

            run_container(output_dir, '/tmp', image_name, psortb_command, env_vars, container_engine=container_engine)

            os.remove(os.path.join(output_dir, file_name))

            # Move results from results_dir to output_dir
            for item in os.listdir(results_dir):
                s = os.path.join(results_dir, item)
                d = os.path.join(output_dir, item)
                if os.path.isdir(s):
                    shutil.move(s, d)
                else:
                    shutil.move(s, d)
            os.rmdir(results_dir)


            logging.info(f"Psort results in '{output_dir}'.")
        else:
            logging.error(f"Directory '{output_dir}' not found.")
    else:
        logging.error(f"Directory '{input}' not found.")

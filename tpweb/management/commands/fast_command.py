import os
import sys
import yaml
import subprocess as sp
import gzip
import signal
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biodatabase import Biodatabase
import pandas as pd
import shutil

from tpweb.services.genome_workspace import display_genome_name

class Command(BaseCommand):
    help = '''Takes genome genkbak indentifier, modify the config.py
              of fasttarget and runs the pipeline.'''

    def add_arguments(self, parser):
        parser.add_argument('genome')
        parser.add_argument('folder_path')
        parser.add_argument('--overwrite', action="store_true")
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        def _flag_enabled(name, default=False):
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        genome = options['genome']
        folder_path = options['folder_path']
        datadir = options['datadir']
        gbk_path = os.path.join(folder_path, f"{genome}.gbk")
        gbk_path_gz = os.path.join(folder_path, f"{genome}.gbk.gz")
        bioentry = (
            Bioentry.objects.filter(biodatabase__name=genome).first()
            or Bioentry.objects.filter(identifier=genome).first()
            or Bioentry.objects.filter(identifier=display_genome_name(genome)).first()
            or Bioentry.objects.filter(accession=genome).first()
            or Bioentry.objects.filter(accession=display_genome_name(genome)).first()
        )
        if bioentry is None or bioentry.taxon is None:
            raise CommandError(
                f"Unable to resolve taxonomy for genome '{genome}'. "
                "Expected a Bioentry in the imported biodatabase before running FastTarget."
            )
        taxon = bioentry.taxon
        name = options['genome']
        taxon_id = taxon.ncbi_taxon_id
        input_filename = "/app/fasttarget/config.yml"
        ss = SeqStore(datadir)
        allow_fallback = _flag_enabled("TPW_FASTTARGET_ALLOW_FALLBACK", default=False)
        skip_exec = _flag_enabled("TPW_FASTTARGET_SKIP_EXEC", default=False)

        min_free_gb_raw = os.getenv("TPW_FASTTARGET_MIN_FREE_GB", "0")
        try:
            min_free_gb = float(min_free_gb_raw)
        except ValueError as exc:
            raise CommandError(
                f"Invalid TPW_FASTTARGET_MIN_FREE_GB='{min_free_gb_raw}'. Expected number."
            ) from exc
        free_gb = shutil.disk_usage("/app/fasttarget").free / (1024 ** 3)
        if min_free_gb > 0 and free_gb < min_free_gb:
            if not allow_fallback:
                raise CommandError(
                    f"Low disk space for FastTarget: free={free_gb:.1f}GB, required>={min_free_gb:.1f}GB. "
                    "Enable fallback mode with TPW_FASTTARGET_ALLOW_FALLBACK=1 to continue safely."
                )
            skip_exec = True
            self.stderr.write(self.style.WARNING(
                f"Low disk space detected (free={free_gb:.1f}GB). Skipping fasttarget.py and using fallback tables."
            ))

        if not os.path.exists(gbk_path):
            with gzip.open(gbk_path_gz, 'rb') as f_in:
                with open(gbk_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

        if not os.path.exists(input_filename):
            raise CommandError(
                f"Missing FastTarget config: {input_filename}. "
                "Check that /app/fasttarget is mounted and initialized."
            )

        with open(input_filename, 'r') as file:
            config = yaml.safe_load(file)

        if config is None:
            print("Error: Unable to parse the YAML file.")
        else:
            config.setdefault('organism', {})
            config['organism']['name'] = name
            config['organism']['tax_id'] = taxon_id
            config['organism']['strain_taxid'] = taxon_id
            config['organism']['gbk_file'] = gbk_path

            config.setdefault('container_engine', 'docker')

            config.setdefault('offtarget', {})
            config['offtarget']['enabled'] = True
            config['offtarget']['human'] = True
            config['offtarget']['microbiome'] = True
            config['offtarget'].setdefault('microbiome_identity_filter', 40)
            config['offtarget'].setdefault('microbiome_coverage_filter', 70)
            config['offtarget'].setdefault('foldseek_human', False)

            config.setdefault('deg', {})
            config['deg']['enabled'] = True
            config['deg'].setdefault('deg_identity_filter', 40)
            config['deg'].setdefault('deg_coverage_filter', 70)

            ft_cpus_raw = os.getenv("TPW_FASTTARGET_CPUS", "").strip()
            if ft_cpus_raw:
                try:
                    ft_cpus = int(ft_cpus_raw)
                except ValueError as exc:
                    raise CommandError(
                        f"Invalid TPW_FASTTARGET_CPUS='{ft_cpus_raw}'. Expected integer > 0."
                    ) from exc
                if ft_cpus <= 0:
                    raise CommandError(
                        f"Invalid TPW_FASTTARGET_CPUS='{ft_cpus_raw}'. Expected integer > 0."
                    )
                config['cpus'] = ft_cpus
        with open(input_filename, 'w') as file:
            yaml.safe_dump(config, file)

        # mcpalumbo's fasttarget does NOT auto-download DBs from fasttarget.py.
        # Bootstrap missing ones before invoking the pipeline. The DB dir is
        # typically a mounted volume (TPW_FASTTARGET_DB_DIR) so downloads
        # persist across runs.
        db_dir = "/app/fasttarget/databases"
        if not skip_exec:
            downloads = []
            if not os.path.exists(os.path.join(db_dir, "HUMAN_DB.phr")):
                downloads.append("human-sequences")
            if not os.path.exists(os.path.join(db_dir, "DEG_DB.phr")):
                downloads.append("deg")
            species_dir = os.path.join(db_dir, "species_catalogue")
            if not os.path.isdir(species_dir) or not os.listdir(species_dir):
                downloads.append("microbiome")
            for db_name in downloads:
                self.stderr.write(self.style.WARNING(
                    f"FastTarget DB missing: bootstrapping '{db_name}' into {db_dir}"
                ))
                boot_cmd = [
                    sys.executable,
                    "/app/fasttarget/databases.py",
                    "--download", db_name,
                    "--database-path", db_dir,
                ]
                boot = sp.run(boot_cmd, capture_output=True, text=True)
                print(boot.stdout, boot.stderr)
                if boot.returncode != 0 and not allow_fallback:
                    raise CommandError(
                        f"Failed to download FastTarget DB '{db_name}' (rc={boot.returncode})."
                    )

        command = [sys.executable, "/app/fasttarget/fasttarget.py"]
        if skip_exec and not allow_fallback:
            raise CommandError(
                "TPW_FASTTARGET_SKIP_EXEC=1 requires TPW_FASTTARGET_ALLOW_FALLBACK=1."
            )
        timeout_raw = os.getenv("FASTTARGET_TIMEOUT_SEC", "0")
        try:
            timeout_sec = int(timeout_raw)
        except ValueError as exc:
            raise CommandError(
                f"Invalid FASTTARGET_TIMEOUT_SEC='{timeout_raw}'. Expected integer seconds."
            ) from exc
        if skip_exec:
            results = sp.CompletedProcess(command, 0, stdout="", stderr="")
            self.stderr.write(self.style.WARNING(
                "Skipping fasttarget.py execution by TPW_FASTTARGET_SKIP_EXEC=1. "
                "Using fallback score tables when needed."
            ))
        else:
            try:
                if timeout_sec > 0:
                    proc = sp.Popen(
                        command,
                        stdout=sp.PIPE,
                        stderr=sp.PIPE,
                        text=True,
                        start_new_session=True,
                    )
                    try:
                        stdout, stderr = proc.communicate(timeout=timeout_sec)
                    except sp.TimeoutExpired as exc:
                        os.killpg(proc.pid, signal.SIGTERM)
                        try:
                            stdout, stderr = proc.communicate(timeout=10)
                        except sp.TimeoutExpired:
                            os.killpg(proc.pid, signal.SIGKILL)
                            stdout, stderr = proc.communicate()
                        raise sp.TimeoutExpired(command, timeout_sec, output=stdout, stderr=stderr) from exc
                    results = sp.CompletedProcess(command, proc.returncode, stdout=stdout, stderr=stderr)
                else:
                    results = sp.run(command, capture_output=True, text=True)
            except sp.TimeoutExpired as exc:
                if not allow_fallback:
                    raise CommandError(
                        f"fasttarget.py timed out after {timeout_sec}s and fallback is disabled "
                        "(set TPW_FASTTARGET_ALLOW_FALLBACK=1 to allow fallback tables)."
                    )
                results = sp.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=exc.stderr or "")
                self.stderr.write(self.style.WARNING(
                    f"fasttarget.py timed out after {timeout_sec}s. Using fallback score tables when needed."
                ))
        print(results.stdout, results.stderr)
        if results.returncode != 0:
            if not allow_fallback:
                raise CommandError(
                    f"fasttarget.py exited with code {results.returncode} and fallback is disabled "
                    "(set TPW_FASTTARGET_ALLOW_FALLBACK=1 to allow fallback tables)."
                )
            self.stderr.write(self.style.WARNING(
                f"fasttarget.py exited with code {results.returncode}. Using fallback score tables when needed."
            ))

        def _all_genes():
            proteome_name = f"{genome}{Biodatabase.PROT_POSTFIX}"
            genes = list(
                Bioentry.objects.filter(
                    biodatabase__name=proteome_name,
                ).values_list("accession", flat=True)
            )
            if genes:
                return sorted({g for g in genes if g})

            genes = []
            faa = os.path.join(folder_path, f"{genome}.faa")
            faa_gz = os.path.join(folder_path, f"{genome}.faa.gz")
            if os.path.exists(faa):
                with open(faa, "r") as fh:
                    for line in fh:
                        if line.startswith(">"):
                            genes.append(line[1:].split()[0].strip())
            elif os.path.exists(faa_gz):
                with gzip.open(faa_gz, "rt") as fh:
                    for line in fh:
                        if line.startswith(">"):
                            genes.append(line[1:].split()[0].strip())
            if genes:
                return sorted({g for g in genes if g})

            genes = list(
                Bioentry.objects.filter(
                    taxon=taxon,
                    biodatabase__name=proteome_name,
                ).values_list("accession", flat=True)
            )
            if not genes:
                genes = list(
                    Bioentry.objects.filter(
                        taxon=taxon
                    ).values_list("accession", flat=True)
                )
            return sorted({g for g in genes if g})

        def _write_fallback(path, column, default_value):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            genes = _all_genes()
            df = pd.DataFrame({"gene": genes, column: [default_value] * len(genes)})
            df.to_csv(path, index=False, sep="\t")
            self.stderr.write(self.style.WARNING(f"Fallback generated: {path}"))

        tables_dir = f"/app/fasttarget/organism/{name}/tables_for_TP"

        human_src = os.path.join(tables_dir, "human_offtarget.tsv")
        human_out = ss.human_offtarget(genome)
        if os.path.exists(human_src):
            human = pd.read_csv(human_src, sep="\t")
            human.to_csv(human_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(f"Missing required FastTarget output: {human_src}")
            _write_fallback(human_out, "human_offtarget", "no_hit")

        # mcpalumbo's fasttarget emits per-species counts (gut_microbiome_offtarget_counts.tsv)
        # instead of the legacy hit/no_hit column. Adapt to the TP score shape here:
        # any species with >=1 hit (count > 0) → "hit", else "no_hit".
        micro_counts_src = os.path.join(tables_dir, "gut_microbiome_offtarget_counts.tsv")
        micro_legacy_src = os.path.join(tables_dir, "gut_microbiome_offtarget.tsv")
        micro_out = ss.micro_offtarget(genome)
        if os.path.exists(micro_counts_src):
            micro = pd.read_csv(micro_counts_src, sep="\t")
            count_col = next(
                (c for c in micro.columns if c != "gene"),
                None,
            )
            if count_col is None:
                raise CommandError(
                    f"Unexpected schema in {micro_counts_src}: missing value column."
                )
            micro["gut_microbiome_offtarget"] = micro[count_col].apply(
                lambda v: "hit" if pd.notna(v) and float(v) > 0 else "no_hit"
            )
            micro[["gene", "gut_microbiome_offtarget"]].to_csv(micro_out, index=False, sep="\t")
        elif os.path.exists(micro_legacy_src):
            micro = pd.read_csv(micro_legacy_src, sep="\t")
            micro.to_csv(micro_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(
                    f"Missing required FastTarget output: {micro_counts_src} (or legacy {micro_legacy_src})"
                )
            _write_fallback(micro_out, "gut_microbiome_offtarget", "no_hit")

        deg_src = os.path.join(tables_dir, "hit_in_deg.tsv")
        deg_out = ss.essenciality(genome)
        if os.path.exists(deg_src):
            shutil.copy2(deg_src, deg_out)
        else:
            if not allow_fallback:
                raise CommandError(f"Missing required FastTarget output: {deg_src}")
            _write_fallback(deg_out, "hit_in_deg", "N")

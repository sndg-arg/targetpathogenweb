import os
import yaml
import subprocess as sp
import gzip
import signal
from django.core.management.base import BaseCommand, CommandError
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
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
            config['organism']['name'] = name
            config['organism']['tax_id'] = taxon_id
            config['organism']['gbk_file'] = gbk_path
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

        command = ["python", "/app/fasttarget/fasttarget.py"]
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
                    biodatabase__name=f"{genome}_prots"
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

        micro_src = os.path.join(tables_dir, "gut_microbiome_offtarget.tsv")
        micro_out = ss.micro_offtarget(genome)
        if os.path.exists(micro_src):
            micro = pd.read_csv(micro_src, sep="\t")
            micro.to_csv(micro_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(f"Missing required FastTarget output: {micro_src}")
            _write_fallback(micro_out, "gut_microbiome_offtarget", "no_hit")

        deg_src = os.path.join(tables_dir, "hit_in_deg.tsv")
        deg_out = ss.essenciality(genome)
        if os.path.exists(deg_src):
            shutil.copy2(deg_src, deg_out)
        else:
            if not allow_fallback:
                raise CommandError(f"Missing required FastTarget output: {deg_src}")
            _write_fallback(deg_out, "hit_in_deg", "N")

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

        def _write_fallback_table(path, values):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            genes = _all_genes()
            df = pd.DataFrame({"gene": genes})
            for column, default_value in values.items():
                df[column] = [default_value] * len(genes)
            df.to_csv(path, index=False, sep="\t")
            self.stderr.write(self.style.WARNING(f"Fallback generated: {path}"))

        def _find_existing(*paths):
            return next((path for path in paths if os.path.exists(path)), None)

        def _as_hit_no_hit(value):
            normalized = str(value).strip().lower()
            return "no_hit" if normalized in {"", "none", "nan", "no_hit", "no hit"} else "hit"

        def _as_yes_no(value):
            normalized = str(value).strip().lower()
            return "Y" if normalized in {"true", "t", "1", "yes", "y", "hit"} else "N"

        def _best_blast_metrics(path):
            if not path or not os.path.exists(path) or os.path.getsize(path) <= 0:
                return pd.DataFrame(columns=["gene", "identity", "evalue"])
            blast_columns = [
                "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
                "qstart", "qend", "sstart", "send", "evalue", "bitscore",
                "qcovhsp", "qcovs",
            ]
            blast = pd.read_csv(path, sep="\t", header=None)
            if blast.empty:
                return pd.DataFrame(columns=["gene", "identity", "evalue"])
            if str(blast.iloc[0, 0]).strip().lower() == "qseqid":
                blast = blast.iloc[1:].reset_index(drop=True)
            blast = blast.iloc[:, :min(len(blast.columns), len(blast_columns))]
            blast.columns = blast_columns[:len(blast.columns)]
            required = {"qseqid", "pident", "evalue"}
            if not required.issubset(set(blast.columns)):
                return pd.DataFrame(columns=["gene", "identity", "evalue"])
            blast = blast.rename(columns={"qseqid": "gene", "pident": "identity"})
            blast["identity"] = pd.to_numeric(blast["identity"], errors="coerce")
            blast["evalue"] = pd.to_numeric(blast["evalue"], errors="coerce")
            blast = blast.dropna(subset=["gene", "identity", "evalue"])
            if blast.empty:
                return pd.DataFrame(columns=["gene", "identity", "evalue"])
            blast = blast.sort_values(["gene", "identity", "evalue"], ascending=[True, False, True])
            return blast.groupby("gene", as_index=False).first()[["gene", "identity", "evalue"]]

        def _numeric_column(df, column, default_value):
            if column not in df.columns:
                return pd.Series([default_value] * len(df), index=df.index)
            return pd.to_numeric(df[column], errors="coerce").fillna(default_value)

        organism_dir = f"/app/fasttarget/organism/{name}"
        tables_dir = os.path.join(organism_dir, "tables_for_TP")
        offtarget_dir = os.path.join(organism_dir, "offtarget")
        essentiality_dir = os.path.join(organism_dir, "essentiality")

        human_src = _find_existing(
            os.path.join(tables_dir, "human_offtarget.tsv"),
            os.path.join(offtarget_dir, "human_offtarget.tsv"),
        )
        human_blast_src = _find_existing(
            os.path.join(tables_dir, "human_offtarget_blast.tsv"),
            os.path.join(offtarget_dir, "human_offtarget_blast.tsv"),
        )
        human_out = ss.human_offtarget(genome)
        if human_src:
            human = pd.read_csv(human_src, sep="\t")
            if "gene" not in human.columns or "human_offtarget" not in human.columns:
                raise CommandError(f"Unexpected schema in {human_src}: expected gene,human_offtarget.")
            human = human.copy()
            blast_metrics = _best_blast_metrics(human_blast_src).rename(
                columns={"identity": "human_identity", "evalue": "human_evalue"}
            )
            if not blast_metrics.empty:
                human = human.merge(blast_metrics, on="gene", how="left", suffixes=("", "_blast"))
                if "human_identity_blast" in human.columns and "human_identity" not in human.columns:
                    human["human_identity"] = human["human_identity_blast"]
                if "human_evalue_blast" in human.columns and "human_evalue" not in human.columns:
                    human["human_evalue"] = human["human_evalue_blast"]
            if "human_identity" not in human.columns:
                human["human_identity"] = _numeric_column(human, "human_offtarget", 0)
            else:
                human["human_identity"] = _numeric_column(human, "human_identity", 0)
            human["human_evalue"] = _numeric_column(human, "human_evalue", 1)
            human["human_offtarget"] = human["human_offtarget"].apply(_as_hit_no_hit)
            human[["gene", "human_offtarget", "human_identity", "human_evalue"]].to_csv(human_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(
                    f"Missing required FastTarget output: {os.path.join(tables_dir, 'human_offtarget.tsv')} "
                    f"or {os.path.join(offtarget_dir, 'human_offtarget.tsv')}"
                )
            _write_fallback_table(
                human_out,
                {"human_offtarget": "no_hit", "human_identity": 0, "human_evalue": 1},
            )

        # mcpalumbo's fasttarget emits per-species counts (gut_microbiome_offtarget_counts.tsv)
        # instead of the legacy hit/no_hit column. Adapt to the TP score shape here:
        # any species with >=1 hit (count > 0) → "hit", else "no_hit".
        micro_counts_src = _find_existing(
            os.path.join(tables_dir, "gut_microbiome_offtarget_counts.tsv"),
            os.path.join(offtarget_dir, "gut_microbiome_offtarget_counts.tsv"),
        )
        micro_legacy_src = _find_existing(
            os.path.join(tables_dir, "gut_microbiome_offtarget.tsv"),
            os.path.join(offtarget_dir, "gut_microbiome_offtarget.tsv"),
        )
        micro_species_dir = os.path.join(offtarget_dir, "species_blast_results")
        micro_out = ss.micro_offtarget(genome)
        if micro_counts_src:
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
        elif micro_legacy_src:
            micro = pd.read_csv(micro_legacy_src, sep="\t")
            if "gene" not in micro.columns or "gut_microbiome_offtarget" not in micro.columns:
                raise CommandError(
                    f"Unexpected schema in {micro_legacy_src}: expected gene,gut_microbiome_offtarget."
                )
            micro["gut_microbiome_offtarget"] = micro["gut_microbiome_offtarget"].apply(_as_hit_no_hit)
            micro[["gene", "gut_microbiome_offtarget"]].to_csv(micro_out, index=False, sep="\t")
        elif os.path.isdir(micro_species_dir):
            hit_genes = set()
            for root, _, files in os.walk(micro_species_dir):
                for filename in files:
                    if not filename.endswith("_offtarget.tsv"):
                        continue
                    path = os.path.join(root, filename)
                    if os.path.getsize(path) <= 0:
                        continue
                    with open(path, "r") as handle:
                        for line in handle:
                            parts = line.strip().split("\t")
                            if parts and parts[0]:
                                hit_genes.add(parts[0])
            genes = _all_genes()
            micro = pd.DataFrame({
                "gene": genes,
                "gut_microbiome_offtarget": [
                    "hit" if gene in hit_genes else "no_hit" for gene in genes
                ],
            })
            micro.to_csv(micro_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(
                    "Missing required FastTarget microbiome output: "
                    f"{os.path.join(tables_dir, 'gut_microbiome_offtarget_counts.tsv')}, "
                    f"{os.path.join(offtarget_dir, 'gut_microbiome_offtarget_counts.tsv')}, "
                    f"or {micro_species_dir}"
                )
            _write_fallback(micro_out, "gut_microbiome_offtarget", "no_hit")

        deg_src = _find_existing(
            os.path.join(tables_dir, "hit_in_deg.tsv"),
            os.path.join(essentiality_dir, "hit_in_deg.tsv"),
        )
        deg_blast_src = _find_existing(
            os.path.join(tables_dir, "deg_blast.tsv"),
            os.path.join(essentiality_dir, "deg_blast.tsv"),
        )
        deg_out = ss.essenciality(genome)
        if deg_src:
            deg = pd.read_csv(deg_src, sep="\t")
            if "gene" not in deg.columns or "hit_in_deg" not in deg.columns:
                raise CommandError(f"Unexpected schema in {deg_src}: expected gene,hit_in_deg.")
            deg = deg.copy()
            blast_metrics = _best_blast_metrics(deg_blast_src).rename(
                columns={"identity": "deg_identity", "evalue": "deg_evalue"}
            )
            if not blast_metrics.empty:
                deg = deg.merge(blast_metrics, on="gene", how="left", suffixes=("", "_blast"))
                if "deg_identity_blast" in deg.columns and "deg_identity" not in deg.columns:
                    deg["deg_identity"] = deg["deg_identity_blast"]
                if "deg_evalue_blast" in deg.columns and "deg_evalue" not in deg.columns:
                    deg["deg_evalue"] = deg["deg_evalue_blast"]
            deg["deg_identity"] = _numeric_column(deg, "deg_identity", 0)
            deg["deg_evalue"] = _numeric_column(deg, "deg_evalue", 1)
            deg["hit_in_deg"] = deg["hit_in_deg"].apply(_as_yes_no)
            deg[["gene", "hit_in_deg", "deg_identity", "deg_evalue"]].to_csv(deg_out, index=False, sep="\t")
        else:
            if not allow_fallback:
                raise CommandError(
                    f"Missing required FastTarget output: {os.path.join(tables_dir, 'hit_in_deg.tsv')} "
                    f"or {os.path.join(essentiality_dir, 'hit_in_deg.tsv')}"
                )
            _write_fallback_table(
                deg_out,
                {"hit_in_deg": "N", "deg_identity": 0, "deg_evalue": 1},
            )

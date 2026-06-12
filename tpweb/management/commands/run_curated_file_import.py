import contextlib
import io
import math
import os
import shlex
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.services.curated_pipeline import build_curated_pipeline_plan, compute_folder_path


KNOWN_ARCHIVE_DIRS = (
    "genome",
    "structures",
    "offtarget",
    "essentiality",
    "ligq2",
    "LigQ_2",
    "ligq_2",
)

GBK_SUFFIXES = (".gbk", ".gbk.gz", ".gbff", ".gbff.gz")


@dataclass
class ArchiveLayout:
    root: str = ""
    dirs: dict[str, str] = field(default_factory=dict)
    gbk_members: list[str] = field(default_factory=list)
    ligq_members: list[str] = field(default_factory=list)


class Command(BaseCommand):
    help = (
        "Validate and orchestrate a curated file import from a results TSV plus "
        "an optional archive. Defaults to a dry-run; pass --execute to write."
    )

    def add_arguments(self, parser):
        parser.add_argument("--genome", required=True, help="Internal TPW genome name, e.g. public__KpKP13.")
        parser.add_argument("--display-name", default=None, help="Human-readable name used only in reports.")
        parser.add_argument("--gram", default="n", choices=("n", "p"), help="Gram stain flag for generated pipeline commands.")
        parser.add_argument("--results-tsv", required=True, help="Curated results_table.tsv.")
        parser.add_argument("--archive", default=None, help="Optional tar/tar.gz archive with genome/structures/results folders.")
        parser.add_argument("--structures-dir", default=None, help="Optional already-extracted structures directory.")
        parser.add_argument("--ligq-output-dir", default=None, help="Optional already-existing LigQ_2 output directory.")
        parser.add_argument("--archive-root", default=None, help="Expected top-level archive directory. Auto-detected if omitted.")
        parser.add_argument("--datadir", default="./data", help="TPW data directory.")
        parser.add_argument(
            "--workdir",
            default=None,
            help="Project working directory for generated commands. Defaults to the parent of --datadir when it ends in /data.",
        )
        parser.add_argument(
            "--report",
            default=None,
            help="Optional path to write the dry-run/execution report.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "Run the safe local import steps. Without this flag the command only validates "
                "inputs and prints the plan."
            ),
        )
        parser.add_argument(
            "--overwrite-scores",
            action="store_true",
            help="Pass --overwrite to score imports. Structures are still preserved by their loaders.",
        )
        parser.add_argument(
            "--extract",
            action="store_true",
            help=(
                "Extract required archive folders into <genome>/curated_import/extracted. "
                "Required for --execute when --archive is used and no extracted folders exist."
            ),
        )
        parser.add_argument(
            "--overwrite-extract",
            action="store_true",
            help="Allow replacing files in the curated_import/extracted workspace only.",
        )
        parser.add_argument(
            "--skip-uniprot-backfill",
            action="store_true",
            help="Do not run backfill_curated_uniprot_annotations during --execute.",
        )
        parser.add_argument(
            "--skip-experimental-fetch",
            action="store_true",
            help="Do not run fetch_experimental_structures --all-xrefs during --execute.",
        )
        parser.add_argument(
            "--skip-ligq",
            action="store_true",
            help="Do not run load_ligq_2_results during --execute even if LigQ output is detected.",
        )

    def handle(self, *args, **options):
        genome = options["genome"].strip()
        datadir = options["datadir"]
        folder_path = compute_folder_path(datadir, genome)
        workdir = _resolve_workdir(options["workdir"], datadir)

        report_lines = []
        self._line(report_lines, f"Curated file import plan for {genome}")
        if options["display_name"]:
            self._line(report_lines, f"Display name: {options['display_name']}")
        self._line(report_lines, f"Mode: {'execute' if options['execute'] else 'dry-run'}")
        self._line(report_lines, f"Data folder: {folder_path}")
        self._line(report_lines, "")

        tsv_info = self._validate_results_tsv(options["results_tsv"], report_lines)
        layout = None
        extract_root = Path(folder_path) / "curated_import" / "extracted"

        if options["archive"]:
            layout = self._inspect_archive(
                options["archive"],
                options["archive_root"],
                report_lines,
            )
            if options["execute"] and options["extract"]:
                self._extract_archive(
                    options["archive"],
                    layout,
                    extract_root,
                    overwrite=options["overwrite_extract"],
                    report_lines=report_lines,
                )
        else:
            self._line(report_lines, "Archive: not provided")

        db = Biodatabase.objects.filter(name=genome + Biodatabase.PROT_POSTFIX).first()
        if db is None:
            self._line(report_lines, "")
            self._line(report_lines, "Genome is not loaded in TPW yet.")
            gbk_hint = self._first_gbk_path(layout, extract_root) if layout else None
            if gbk_hint:
                self._line(report_lines, "Detected GBK/GBFF candidate:")
                self._line(report_lines, f"  {gbk_hint}")
            self._line(report_lines, "Generated next command:")
            self._line(
                report_lines,
                "  "
                + _quote_join(
                    [
                        "/opt/conda/envs/tpv2/bin/python",
                        "pipeline/run_pipeline_direct.py",
                        genome,
                        "--genome-name",
                        genome,
                        "--gram",
                        options["gram"],
                        "--start-stage",
                        "2",
                        "--stop-stage",
                        "3",
                        "--no-local-heavy",
                    ]
                ),
            )
            self._write_report(options["report"], report_lines)
            self.stdout.write("\n".join(report_lines))
            if options["execute"]:
                raise CommandError(
                    "Genome is not loaded yet. Load the GBK first, then rerun this command. "
                    "This MVP does not create new genomes automatically."
                )
            return

        self._validate_locus_compatibility(db, tsv_info["genes"], report_lines)

        structures_dir = options.get("structures_dir") or (self._detected_path(layout, extract_root, "structures") if layout else None)
        ligq_dir = options.get("ligq_output_dir") or (self._detect_ligq_path(layout, extract_root) if layout else None)
        gbk_path = self._first_gbk_path(layout, extract_root) if layout else None

        self._line(report_lines, "")
        self._line(report_lines, "Detected usable inputs")
        self._line(report_lines, f"  structures: {structures_dir or '-'}")
        self._line(report_lines, f"  GBK/GBFF: {gbk_path or '-'}")
        self._line(report_lines, f"  LigQ_2: {ligq_dir or '-'}")

        self._line(report_lines, "")
        self._line(report_lines, "Safe local steps")
        self._line(report_lines, f"  import_external_results: {'will run' if options['execute'] else 'would run'}")
        self._line(report_lines, f"  sync_genome_metadata: {'will run' if options['execute'] and gbk_path else 'would run' if gbk_path else 'not available'}")
        self._line(
            report_lines,
            "  backfill_curated_uniprot_annotations: "
            + ("skipped by option" if options["skip_uniprot_backfill"] else "will run" if options["execute"] else "would run"),
        )
        self._line(
            report_lines,
            "  fetch_experimental_structures --all-xrefs: "
            + ("skipped by option" if options["skip_experimental_fetch"] else "will run" if options["execute"] else "would run"),
        )
        self._line(
            report_lines,
            "  load_ligq_2_results: "
            + ("skipped" if options["skip_ligq"] or not ligq_dir else "will run" if options["execute"] else "would run"),
        )

        if options["execute"]:
            self._run_safe_steps(
                genome=genome,
                results_tsv=options["results_tsv"],
                datadir=datadir,
                structures_dir=structures_dir,
                gbk_path=gbk_path,
                ligq_dir=ligq_dir,
                overwrite_scores=options["overwrite_scores"],
                skip_uniprot_backfill=options["skip_uniprot_backfill"],
                skip_experimental_fetch=options["skip_experimental_fetch"],
                skip_ligq=options["skip_ligq"],
                report_lines=report_lines,
            )

        plan = build_curated_pipeline_plan(genome, results_tsv=options["results_tsv"], datadir=datadir)
        self._append_plan_summary(plan, workdir, options["gram"], report_lines)

        self._write_report(options["report"], report_lines)
        self.stdout.write("\n".join(report_lines))

    def _validate_results_tsv(self, path, report_lines):
        if not os.path.isfile(path):
            raise CommandError(f"Results TSV not found: {path}")
        try:
            df = pd.read_csv(path, sep="\t", low_memory=False)
        except Exception as exc:
            raise CommandError(f"Could not read results TSV {path}: {exc}") from exc
        if "gene" not in df.columns:
            raise CommandError("Results TSV must contain a 'gene' column.")

        genes = [str(g).strip() for g in df["gene"].dropna()]
        genes = [g for g in genes if g]
        if not genes:
            raise CommandError("Results TSV has no non-empty gene values.")

        self._line(report_lines, "Results TSV")
        self._line(report_lines, f"  path: {path}")
        self._line(report_lines, f"  rows: {len(df)}")
        self._line(report_lines, f"  unique genes: {len(set(genes))}")
        self._line(report_lines, f"  columns: {', '.join(df.columns)}")
        return {"rows": len(df), "genes": set(genes), "columns": list(df.columns)}

    def _inspect_archive(self, archive_path, requested_root, report_lines):
        if not os.path.isfile(archive_path):
            raise CommandError(f"Archive not found: {archive_path}")

        try:
            with tarfile.open(archive_path, "r:*") as tar:
                members = [m for m in tar.getmembers() if m.name and not _unsafe_member(m.name)]
        except tarfile.TarError as exc:
            raise CommandError(f"Could not read archive {archive_path}: {exc}") from exc

        if not members:
            raise CommandError(f"Archive has no safe members: {archive_path}")

        root = requested_root.strip("/\\") if requested_root else _detect_archive_root(m.name for m in members)
        layout = ArchiveLayout(root=root)

        for member in members:
            rel = _strip_root(member.name, root)
            if not rel:
                continue
            first = rel.split("/", 1)[0]
            if first in KNOWN_ARCHIVE_DIRS and first not in layout.dirs:
                layout.dirs[first] = rel.split("/", 1)[0]
            lower = rel.lower()
            if lower.endswith(GBK_SUFFIXES):
                layout.gbk_members.append(rel)
            if "ligq" in lower and lower.endswith((".tsv", ".csv")):
                layout.ligq_members.append(rel)

        self._line(report_lines, "")
        self._line(report_lines, "Archive")
        self._line(report_lines, f"  path: {archive_path}")
        self._line(report_lines, f"  root: {layout.root or '-'}")
        self._line(report_lines, f"  detected folders: {', '.join(sorted(layout.dirs)) or '-'}")
        self._line(report_lines, f"  GBK/GBFF candidates: {len(layout.gbk_members)}")
        self._line(report_lines, f"  LigQ-like TSV/CSV files: {len(layout.ligq_members)}")
        return layout

    def _extract_archive(self, archive_path, layout, extract_root, *, overwrite, report_lines):
        extract_root = Path(extract_root)
        if extract_root.exists() and any(extract_root.iterdir()) and not overwrite:
            raise CommandError(
                f"Extraction workspace already exists and is not empty: {extract_root}. "
                "Pass --overwrite-extract to replace files inside that workspace."
            )
        extract_root.mkdir(parents=True, exist_ok=True)

        wanted_prefixes = set(layout.dirs.values())
        wanted_prefixes.update(member.split("/", 1)[0] for member in layout.gbk_members)
        if not wanted_prefixes:
            raise CommandError("Archive contains no supported folders or GBK/GBFF files to extract.")

        extracted = 0
        with tarfile.open(archive_path, "r:*") as tar:
            for member in tar.getmembers():
                if _unsafe_member(member.name):
                    continue
                rel = _strip_root(member.name, layout.root)
                if not rel:
                    continue
                first = rel.split("/", 1)[0]
                if first not in wanted_prefixes:
                    continue
                target = extract_root / rel
                if not _is_within(extract_root, target):
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                mode = "wb" if overwrite else "xb"
                with source, target.open(mode) as out:
                    out.write(source.read())
                extracted += 1
        self._line(report_lines, f"Extracted files: {extracted} into {extract_root}")

    def _validate_locus_compatibility(self, db, tsv_genes, report_lines):
        db_genes = set(Bioentry.objects.filter(biodatabase=db).values_list("accession", flat=True))
        overlap = len(db_genes & tsv_genes)
        missing_in_db = len(tsv_genes - db_genes)
        missing_in_tsv = len(db_genes - tsv_genes)
        self._line(report_lines, "")
        self._line(report_lines, "Protein compatibility")
        self._line(report_lines, f"  DB proteins: {len(db_genes)}")
        self._line(report_lines, f"  TSV genes: {len(tsv_genes)}")
        self._line(report_lines, f"  overlap: {overlap}")
        self._line(report_lines, f"  TSV genes missing in DB: {missing_in_db}")
        self._line(report_lines, f"  DB proteins missing in TSV: {missing_in_tsv}")
        if overlap == 0:
            raise CommandError("No overlap between TSV gene values and loaded TPW protein accessions.")
        if overlap < min(len(db_genes), len(tsv_genes)) * 0.8:
            raise CommandError("Low TSV/DB locus overlap. Refusing to continue; check genome name and TSV.")

    def _run_safe_steps(
        self,
        *,
        genome,
        results_tsv,
        datadir,
        structures_dir,
        gbk_path,
        ligq_dir,
        overwrite_scores,
        skip_uniprot_backfill,
        skip_experimental_fetch,
        skip_ligq,
        report_lines,
    ):
        self._line(report_lines, "")
        self._line(report_lines, "Execution log")
        self._call(
            report_lines,
            "import_external_results",
            genome,
            results_tsv=results_tsv,
            structures_dir=structures_dir,
            datadir=datadir,
            overwrite=overwrite_scores,
        )
        if gbk_path:
            self._call(report_lines, "sync_genome_metadata", genome, gbk_path)
        if not skip_uniprot_backfill:
            self._call(
                report_lines,
                "backfill_curated_uniprot_annotations",
                genome,
                results_tsv=results_tsv,
                datadir=datadir,
            )
        if not skip_experimental_fetch:
            self._call(report_lines, "fetch_experimental_structures", genome, datadir=datadir, all_xrefs=True)
        if ligq_dir and not skip_ligq:
            self._call(report_lines, "load_ligq_2_results", ligq_dir)

    def _call(self, report_lines, command_name, *args, **kwargs):
        self._line(report_lines, f"  RUN {command_name}")
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            call_command(command_name, *args, **kwargs)
        for line in out.getvalue().splitlines()[-20:]:
            self._line(report_lines, f"    {line}")
        for line in err.getvalue().splitlines()[-20:]:
            self._line(report_lines, f"    STDERR {line}")

    def _append_plan_summary(self, plan, workdir, gram, report_lines):
        self._line(report_lines, "")
        self._line(report_lines, "Final curated pipeline audit")
        self._line(report_lines, f"  proteins: {plan.protein_total}")
        self._line(report_lines, f"  structures: {plan.protein_structures}/{plan.protein_total}")
        self._line(report_lines, f"  UniProt mapped proteins: {plan.uniprot_mapped_proteins}/{plan.protein_total}")
        self._line(report_lines, f"  GO/EC annotated proteins: {plan.annotation_proteins}/{plan.protein_total}")
        self._line(report_lines, f"  PDB xref proteins: {plan.pdb_xref_proteins}/{plan.protein_total}")
        self._line(report_lines, f"  FPocket pocket sets: {plan.fpocket_sets}")
        self._line(report_lines, f"  P2Rank pocket sets: {plan.p2rank_sets}")
        self._line(report_lines, f"  Binder rows: {plan.binder_count}")
        self._line(report_lines, f"  Skip stages: {plan.skip_stages_text or '-'}")
        self._line(report_lines, f"  Heavy stages that still require SLURM: {plan.required_remote_stages_text or '-'}")
        if plan.warnings:
            self._line(report_lines, "  Warnings:")
            for warning in plan.warnings:
                self._line(report_lines, f"    - {warning}")

        skip_arg = ["--skip-stages", plan.skip_stages_text] if plan.skip_stages_text else []
        resume = [
            "/opt/conda/envs/tpv2/bin/python",
            "pipeline/run_pipeline_direct.py",
            plan.genome_name,
            "--genome-name",
            plan.genome_name,
            "--gram",
            gram,
            "--start-stage",
            "4",
            *skip_arg,
            "--no-local-heavy",
        ]
        self._line(report_lines, "")
        self._line(report_lines, "Generated safe resume command")
        self._line(report_lines, f"  cd {shlex.quote(workdir)}")
        self._line(report_lines, "  " + _quote_join(resume))

    def _detected_path(self, layout, extract_root, key):
        rel = layout.dirs.get(key)
        if not rel:
            return None
        path = Path(extract_root) / rel
        return str(path) if path.exists() else str(path)

    def _detect_ligq_path(self, layout, extract_root):
        for key in ("ligq2", "LigQ_2", "ligq_2"):
            path = self._detected_path(layout, extract_root, key)
            if path:
                return path
        return None

    def _first_gbk_path(self, layout, extract_root):
        if not layout.gbk_members:
            return None
        return str(Path(extract_root) / layout.gbk_members[0])

    def _write_report(self, report_path, report_lines):
        if not report_path:
            return
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    def _line(self, report_lines, text):
        report_lines.append(str(text))


def _resolve_workdir(workdir, datadir):
    if workdir:
        return workdir
    datadir = datadir.rstrip("/\\")
    if datadir.endswith("/data") or datadir.endswith("\\data"):
        return datadir[:-5]
    return "."


def _quote_join(parts):
    return " ".join(shlex.quote(str(part)) for part in parts if str(part))


def _detect_archive_root(member_names):
    first_parts = set()
    for name in member_names:
        clean = name.strip("/")
        if not clean:
            continue
        first_parts.add(clean.split("/", 1)[0])
        if len(first_parts) > 1:
            return ""
    return next(iter(first_parts), "")


def _strip_root(name, root):
    clean = name.replace("\\", "/").strip("/")
    root = (root or "").replace("\\", "/").strip("/")
    if root and clean == root:
        return ""
    if root and clean.startswith(root + "/"):
        return clean[len(root) + 1 :]
    return clean


def _unsafe_member(name):
    clean = name.replace("\\", "/")
    return clean.startswith("/") or clean.startswith("../") or "/../" in clean or clean == ".."


def _is_within(base, target):
    base = Path(base).resolve()
    target = Path(target).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


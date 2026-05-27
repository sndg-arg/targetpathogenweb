import os
import shlex

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from tpweb.services.curated_pipeline import build_curated_pipeline_plan


class Command(BaseCommand):
    help = (
        "Audit a curated genome import and print the safe pipeline resume plan. "
        "This command does not execute heavy work."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument(
            "--results-tsv",
            default=None,
            help="Optional curated results TSV used only for reporting its available columns.",
        )
        parser.add_argument(
            "--datadir",
            default="./data",
            help="TPW data directory.",
        )
        parser.add_argument(
            "--structure-completion-ratio",
            type=float,
            default=0.95,
            help=(
                "Minimum fraction of proteins that must already have structures before "
                "stages 15/16 are skipped. Default: 0.95."
            ),
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        if not Biodatabase.objects.filter(name=genome_name + Biodatabase.PROT_POSTFIX).exists():
            raise CommandError(f"Genome '{genome_name}' not found. Load the GBK first.")

        plan = build_curated_pipeline_plan(
            genome_name,
            results_tsv=options["results_tsv"],
            datadir=options["datadir"],
            structure_completion_ratio=options["structure_completion_ratio"],
        )

        self.stdout.write(self.style.MIGRATE_HEADING(f"Curated pipeline plan for {plan.genome_name}"))
        self.stdout.write(f"Data folder: {plan.folder_path}")
        self.stdout.write(f"Proteins in TPW: {plan.protein_total}")
        if plan.tsv_columns:
            self.stdout.write(f"TSV columns: {', '.join(plan.tsv_columns)}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Loaded score coverage"))
        for name in sorted(plan.score_counts):
            self.stdout.write(f"  {name}: {plan.score_counts[name]}/{plan.protein_total}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Loaded structure/annotation coverage"))
        self.stdout.write(f"  BioentryStructure proteins: {plan.protein_structures}/{plan.protein_total}")
        self.stdout.write(f"  PDB records: {plan.pdb_count}")
        self.stdout.write(f"  FPocket pocket sets: {plan.fpocket_sets}")
        self.stdout.write(f"  P2Rank pocket sets: {plan.p2rank_sets}")
        self.stdout.write(f"  InterPro TSV exists: {plan.interpro_output_exists}")
        self.stdout.write(f"  Proteins with sequence features: {plan.feature_proteins}/{plan.protein_total}")
        self.stdout.write(f"  Proteins with UniProt mapping: {plan.uniprot_mapped_proteins}/{plan.protein_total}")
        self.stdout.write(f"  Proteins with GO/EC annotations: {plan.annotation_proteins}/{plan.protein_total}")
        self.stdout.write(f"  Binder rows: {plan.binder_count}")
        self.stdout.write(f"  LigQ/ZINC binder rows: {plan.ligq_binder_count}")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("FastTarget status"))
        if plan.fasttarget_org_dir:
            self.stdout.write(f"  Pre-computed output found: {plan.fasttarget_org_dir}")
            self.stdout.write(f"  human_offtarget rows: {plan.fasttarget_human_rows}/{plan.protein_total}")
            self.stdout.write(f"  hit_in_deg rows: {plan.fasttarget_deg_rows}/{plan.protein_total}")
            self.stdout.write(f"  Skip-exec possible: {plan.fasttarget_skip_exec_possible}")
        else:
            self.stdout.write("  No pre-computed FastTarget output found in /app/fasttarget/organism/")

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Pipeline decision"))
        self.stdout.write(f"  Skip stages covered by curated/imported data: {plan.skip_stages_text or '-'}")
        self.stdout.write(f"  Heavy stages that still require SLURM: {plan.required_remote_stages_text or '-'}")

        if plan.notes:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Notes"))
            for note in plan.notes:
                self.stdout.write(f"  - {note}")

        if plan.warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Warnings"))
            for warning in plan.warnings:
                self.stdout.write(f"  - {warning}")

        skip_arg = f"--skip-stages {plan.skip_stages_text}" if plan.skip_stages_text else ""

        # Build env prefix for the resume command
        extra_env = ""
        if plan.fasttarget_skip_exec_possible and 4 not in plan.skip_stages:
            extra_env = (
                "TPW_FASTTARGET_SKIP_EXEC=1 "
                f"TPW_FASTTARGET_ORGANISM_DIR={shlex.quote(plan.fasttarget_org_dir)} "
            )

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Resume command"))
        resume_parts = [
            extra_env,
            "/opt/conda/envs/tpv2/bin/python",
            "pipeline/run_pipeline_direct.py",
            plan.genome_name,
            "--genome-name",
            plan.genome_name,
            "--gram n",
            "--start-stage 4",
            skip_arg,
            "--no-local-heavy",
        ]
        self.stdout.write("  " + " ".join(part for part in resume_parts if part))

        if plan.required_remote_stages:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "  Pipeline will pause at the first SLURM-required stage. "
                "Ensure the env vars for each remote stage are configured before launching."
            ))

        if os.getenv("TPW_FORBID_LOCAL_HEAVY", "").strip() != "1":
            self.stdout.write(
                self.style.WARNING(
                    "  TPW_FORBID_LOCAL_HEAVY is not 1 in this process. Keep --no-local-heavy on the command."
                )
            )

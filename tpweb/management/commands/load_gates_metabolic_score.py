"""
load_gates_metabolic_score - import the Gates-project pan-genome metabolic
priority score for KP13 and ATCC43816.

Ingests a single combined pan-genome mapping CSV (one row per pan-genome gene
model, with that gene's mapped locus tag in each strain) and loads five
per-gene columns into each strain via the generic ScoreParam/ScoreParamValue
system (load_score_values): S_gene, reaction_support, n_reactions, quadrant,
priority. This is the Gates team's curated replacement for the primary
metabolic-importance score; the older automatic BioCyc/Pathway Tools metrics
(loaded by load_metabolism) are unaffected and stay under the "Metabolism
(automatic)" category.

Expected CSV columns: KP13_id_mapeado, KP13_estado, ATCC_id_mapeado,
ATCC_estado, S_gene, reaction_support, n_reactions, quadrant, priority.

Because this is a pan-genome model, more than one row can map to the same
real locus tag in a given strain (redundant/paralogous pan-gene splits that
both resolve to the same confirmed ortholog). When that happens, the row
with the highest reaction_support wins (tie-break: highest S_gene) -- rows
whose strain status is "no_mapeado" are dropped for that strain entirely.

Usage
-----
python manage.py load_gates_metabolic_score tabla_final_mapeo_metabolico.csv \\
    --kp13-genome public__KpKP13 \\
    --atcc-genome public__KpATCC43816 \\
    --overwrite
"""

import os
import tempfile

import pandas as pd
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

GATES_METABOLIC_COLUMNS = ["S_gene", "reaction_support", "n_reactions", "quadrant", "priority"]


def dedupe_strain_rows(df, id_col, status_col):
    """Rows for one strain, filtered and collapsed to one row per real locus
    tag. Drops "no_mapeado" (unmapped) rows and rows with no id at all, then
    -- since this is a pan-genome model, more than one row can map to the
    same real locus tag (redundant/paralogous pan-gene splits resolving to
    the same confirmed ortholog) -- keeps only the highest reaction_support
    per locus tag (tie-break: highest S_gene)."""
    mapped = df[df[status_col] != "no_mapeado"].dropna(subset=[id_col])
    return mapped.sort_values(
        ["reaction_support", "S_gene"], ascending=[False, False]
    ).drop_duplicates(subset=[id_col], keep="first")


class Command(BaseCommand):
    help = "Loads the Gates-project pan-genome metabolic priority score for KP13/ATCC43816."

    def add_arguments(self, parser):
        parser.add_argument("mapping_csv", help="combined pan-genome mapping CSV")
        parser.add_argument(
            "--kp13-genome", required=True, help="Target internal accession for KP13"
        )
        parser.add_argument(
            "--atcc-genome", required=True, help="Target internal accession for ATCC43816"
        )
        parser.add_argument("--datadir", default="./data")
        parser.add_argument("--overwrite", action="store_true")

    def handle(self, *args, **options):
        mapping_csv = options["mapping_csv"]
        if not os.path.exists(mapping_csv):
            raise CommandError(f"'{mapping_csv}' does not exist")

        df = pd.read_csv(mapping_csv)
        required = {
            "KP13_id_mapeado",
            "KP13_estado",
            "ATCC_id_mapeado",
            "ATCC_estado",
            *GATES_METABOLIC_COLUMNS,
        }
        missing = required - set(df.columns)
        if missing:
            raise CommandError(f"Missing expected column(s): {', '.join(sorted(missing))}")

        strains = [
            ("KP13", options["kp13_genome"], "KP13_id_mapeado", "KP13_estado"),
            ("ATCC", options["atcc_genome"], "ATCC_id_mapeado", "ATCC_estado"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            for label, genome_name, id_col, status_col in strains:
                mapped = df[df[status_col] != "no_mapeado"].dropna(subset=[id_col])
                if mapped.empty:
                    self.stderr.write(
                        self.style.WARNING(
                            f"No mapped rows for {label} ({genome_name}) -- skipping."
                        )
                    )
                    continue

                deduped = dedupe_strain_rows(df, id_col, status_col)
                dropped = len(mapped) - len(deduped)
                if dropped:
                    self.stderr.write(
                        f"{label}: {dropped} duplicate pan-genome row(s) collapsed onto an "
                        "already-assigned locus tag (kept the highest reaction_support, "
                        "tie-break highest S_gene)."
                    )

                strain_tsv = os.path.join(tmp_dir, f"{label.lower()}_metabolic_gates.tsv")
                out = deduped[[id_col] + GATES_METABOLIC_COLUMNS].rename(columns={id_col: "gene"})
                out.to_csv(strain_tsv, sep="\t", index=False)

                self.stderr.write(
                    f"{label}: loading {len(out)} gene score row(s) into {genome_name}"
                )
                call_command(
                    "load_score_values",
                    genome_name,
                    strain_tsv,
                    datadir=options["datadir"],
                    overwrite=options["overwrite"],
                )

from tpweb.models.Binders import Binders
import pandas as pd
from django.db import IntegrityError
import os
from bioseq.io.SeqStore import SeqStore
from bioseq.models.Bioentry import Bioentry
import subprocess as sp
from django.core.management.base import BaseCommand, CommandError
from tqdm import tqdm


class Command(BaseCommand):
    help = "Load binder ligands from a CSV file into the Binders table."

    def add_arguments(self, parser):
        parser.add_argument("accession")
        parser.add_argument("--overwrite", action="store_true")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--source",
            choices=[Binders.SOURCE_PDB, Binders.SOURCE_PROPOSED],
            default=Binders.SOURCE_PDB,
            help=(
                "Origin of the binders being loaded. Use 'pdb' for ligands extracted from "
                "experimental structures (default) and 'proposed' for virtual-screening or "
                "docking candidates."
            ),
        )
        parser.add_argument(
            "--filename",
            default=None,
            help=(
                "CSV filename inside the genome data folder. Defaults to 'binders.csv' for "
                "pdb sources and 'proposed_binders.csv' for proposed sources."
            ),
        )

    def handle(self, *args, **options):
        ss = SeqStore(options["datadir"])
        genome_folder = ss.db_dir(options["accession"])

        source = options["source"]
        default_filename = (
            "binders.csv" if source == Binders.SOURCE_PDB else "proposed_binders.csv"
        )
        filename = options["filename"] or default_filename
        binders_path = os.path.abspath(f"{genome_folder}/{filename}")

        if not os.path.exists(binders_path):
            raise CommandError(f"Binders file not found: {binders_path}")

        df = pd.read_csv(binders_path)
        locustags = df["Locustag"].unique()
        bioentry_map = {
            be.accession: be
            for be in Bioentry.objects.filter(accession__in=list(locustags))
        }

        has_score_col = "Score" in df.columns
        has_notes_col = "Notes" in df.columns

        for _, row in tqdm(df.iterrows(), total=len(df)):
            bioentry = bioentry_map.get(row["Locustag"])
            if bioentry is None:
                continue

            score = None
            if has_score_col:
                try:
                    score = float(row["Score"]) if pd.notna(row["Score"]) else None
                except (TypeError, ValueError):
                    score = None

            notes = ""
            if has_notes_col and pd.notna(row.get("Notes")):
                notes = str(row["Notes"])

            defaults = {
                "smiles": row["Smiles"],
                "source": source,
                "score": score,
                "notes": notes,
            }

            try:
                Binders.objects.update_or_create(
                    ccd_id=row.get("Ligand ID", ""),
                    pdb_id=row.get("PDB ID", "") or "",
                    uniprot=row.get("Uniprot", "") or "",
                    locustag=bioentry,
                    defaults=defaults,
                )
            except IntegrityError:
                continue

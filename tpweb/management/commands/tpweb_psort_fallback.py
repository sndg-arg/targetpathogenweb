import os

import pandas as pd
from django.core.management.base import BaseCommand

from bioseq.io.SeqStore import SeqStore
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry


class Command(BaseCommand):
    help = "Generate a PSORT fallback TSV when PSORT cannot run in the current environment."

    def add_arguments(self, parser):
        parser.add_argument("genome_name")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--localization",
            default="Unknown",
            help="Fallback localization value to assign to every protein.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        localization = options["localization"]
        seqstore = SeqStore(options["datadir"])

        proteins = Bioentry.objects.filter(
            biodatabase__name=genome_name + Biodatabase.PROT_POSTFIX
        ).order_by("accession")
        rows = [{"gene": protein.accession, "Localization": localization} for protein in proteins]

        db_dir = seqstore.db_dir(genome_name)
        os.makedirs(db_dir, exist_ok=True)
        output_path = os.path.join(db_dir, "psort.tsv")
        pd.DataFrame(rows, columns=["gene", "Localization"]).to_csv(
            output_path,
            sep="\t",
            index=False,
        )

        self.stderr.write(
            f"PSORT fallback generated at {output_path} for {len(rows)} proteins "
            f"with Localization={localization}."
        )

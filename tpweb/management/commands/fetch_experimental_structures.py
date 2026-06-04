import math

from django.core.management.base import BaseCommand

from tpweb.services.experimental_structures import fetch_and_load_experimental_structures


class Command(BaseCommand):
    help = "Download and load best experimental PDB structure for each protein in a genome."

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Genome accession (e.g. GCF_000009045.1)")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--all-xrefs",
            action="store_true",
            help="Download/load every UniProt PDB xref instead of only the best PDB per protein.",
        )

    def handle(self, *args, **options):
        genome = options["genome"]
        datadir = options["datadir"]

        # Derive folder_path the same way the pipeline does
        acclen = len(genome)
        folder_name = genome[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
        folder_path = f"{datadir}/{folder_name}/{genome}"
        working_dir = datadir.rstrip("/").removesuffix("/data") if datadir.endswith("/data") else datadir

        stats = fetch_and_load_experimental_structures(
            genome,
            folder_path,
            working_dir,
            load_all=options["all_xrefs"],
        )
        self.stdout.write(
            f"Done: {stats['loaded']} loaded, {stats['downloaded']} downloaded, "
            f"{stats['skipped']} skipped out of {stats['total']} proteins with PDB xrefs."
        )

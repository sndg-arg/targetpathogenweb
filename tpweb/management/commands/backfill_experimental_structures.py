"""
Backfill experimental PDB structures for already-loaded genomes.

Two-step process per genome:
  1. Query UniProt for PDB cross-references and store them in BioentryDbxref.
  2. Download the best crystal structure per protein from RCSB and load it.

Uses UniProt IDs already stored in the DB (UnipSp / UnipTr dbxrefs), so it
does not require the _unips.lst file to be present on disk.
"""

import math
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref
from tpweb.services.experimental_structures import fetch_and_load_experimental_structures
from tpweb.services.functional_annotations import (
    BATCH_SIZE,
    _fetch_uniprot_batch,
    _persist_pdb_xrefs,
)

DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")


class Command(BaseCommand):
    help = (
        "Backfill experimental PDB structures for already-loaded genomes. "
        "Fetches PDB xrefs from UniProt using mappings already in the database, "
        "then downloads and loads the best crystal structure per protein."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "genomes",
            nargs="*",
            help="Genome accession(s) to process. If omitted, runs for all loaded genomes.",
        )
        parser.add_argument(
            "--datadir",
            default=DEFAULT_DATA_DIR,
            help="Base data directory (default: %(default)s)",
        )
        parser.add_argument(
            "--skip-fetch",
            action="store_true",
            help="Skip UniProt PDB xref fetch; use only xrefs already stored in the DB.",
        )
        parser.add_argument(
            "--all-xrefs",
            action="store_true",
            help="Download/load every UniProt PDB xref instead of only the best PDB per protein.",
        )

    def handle(self, *args, **options):
        datadir = options["datadir"].rstrip("/")
        skip_fetch = options["skip_fetch"]
        genomes_arg = options["genomes"]

        qs = Biodatabase.objects.exclude(name__endswith=Biodatabase.PROT_POSTFIX)
        if genomes_arg:
            qs = qs.filter(name__in=genomes_arg)

        assemblies = list(qs.values_list("name", flat=True))
        if not assemblies:
            self.stdout.write("No matching genomes found.")
            return

        self.stdout.write(f"Backfilling experimental structures for {len(assemblies)} genome(s).")

        for assembly_name in assemblies:
            self.stdout.write(f"\n[{assembly_name}]")

            if not skip_fetch:
                fetched = self._fetch_and_persist_pdb_xrefs(assembly_name)
                self.stdout.write(f"  PDB xrefs stored for {fetched} protein(s).")

            acclen = len(assembly_name)
            folder_name = assembly_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
            folder_path = f"{datadir}/{folder_name}/{assembly_name}"
            working_dir = datadir[: -len("/data")] if datadir.endswith("/data") else datadir

            stats = fetch_and_load_experimental_structures(
                assembly_name,
                folder_path,
                working_dir,
                load_all=options["all_xrefs"],
            )
            self.stdout.write(
                f"  {stats['loaded']} loaded, {stats['downloaded']} downloaded, "
                f"{stats['skipped']} skipped / {stats['total']} proteins with PDB xrefs."
            )

    def _fetch_and_persist_pdb_xrefs(self, assembly_name):
        proteome_name = f"{assembly_name}{Biodatabase.PROT_POSTFIX}"

        links = BioentryDbxref.objects.select_related("bioentry", "dbxref").filter(
            bioentry__biodatabase__name=proteome_name,
            dbxref__dbname__in=["UnipSp", "UnipTr"],
        )

        acc_to_protein = {}
        for link in links:
            acc = link.dbxref.accession
            if acc not in acc_to_protein:
                acc_to_protein[acc] = link.bioentry

        if not acc_to_protein:
            self.stdout.write(f"  No UniProt mappings found for {assembly_name} — skipping xref fetch.")
            return 0

        accessions = list(acc_to_protein.keys())
        self.stdout.write(f"  Querying UniProt for {len(accessions)} accession(s)...")

        stored = 0
        for i in range(0, len(accessions), BATCH_SIZE):
            batch = accessions[i : i + BATCH_SIZE]
            try:
                results = _fetch_uniprot_batch(batch)
                for entry in results:
                    protein = acc_to_protein.get(entry["accession"])
                    if protein and entry["pdb_xrefs"]:
                        _persist_pdb_xrefs(protein, entry["pdb_xrefs"])
                        stored += 1
            except Exception as exc:
                self.stderr.write(f"  Batch {i}–{i + len(batch)} failed: {exc}")
            time.sleep(0.3)

        return stored

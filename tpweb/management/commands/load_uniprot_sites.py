"""
load_uniprot_sites - backfill UniProt active/binding-site features onto a
genome's already-loaded AlphaFold/ColabFold structures.

Why this is a separate command from `fetch_uniprot_annotations`
-----------------------------------------------------------------
`fetch_uniprot_annotations` runs early in the pipeline (gbk2uniprot_map ->
fetch_uniprot_annotations -> alphafold loop -> colabfold -> structures
chain, per CLAUDE.md's stage overview) — before any BioentryStructure rows
for this genome exist. `functional_annotations._persist_uniprot_sites`
needs those rows (it maps a UniProt feature's sequence position directly
onto a PDB `resid`, only for AF/CF structures, whose numbering is 1:1 with
the UniProt canonical sequence). Called that early, it always finds zero
structures and silently does nothing.

This command re-fetches the same UniProt feature data (ft_act_site,
ft_binding, ft_site) and applies `_persist_uniprot_sites` once
alphafold/colabfold/structures-chain have completed. AlphaFold DB positions
use canonical UniProt numbering; ColabFold positions are transferred only
after a high-identity, high-coverage alignment to the local target sequence.
It does not touch EC/GO/PDB annotations.

The current pipelines invoke this command automatically after the structures
stage. It remains available as an explicit command for existing genomes and
recovery/backfill operations.

Experimental (crystal) structures are not covered here or anywhere in this
pass — see functional_annotations.MODEL_STRUCTURE_EXPERIMENTS and its
docstring for why.

Usage
-----
python manage.py load_uniprot_sites GCF_000009045.1 --datadir /app/.../data [--dry-run]
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from tpweb.services.functional_annotations import (
    load_uniprot_sites_for_genome,
)
from tpweb.services.structure_files import mid_shard

DEFAULT_DATA_DIR = str(settings.BASE_DIR / "data")


class Command(BaseCommand):
    help = (
        "Backfill UniProt active/binding-site features onto a genome's "
        "already-loaded AlphaFold/ColabFold structures."
    )

    def add_arguments(self, parser):
        parser.add_argument("assembly_name", help="Genome accession (e.g. GCF_000009045.1)")
        parser.add_argument(
            "--datadir",
            default=DEFAULT_DATA_DIR,
            help="Base data directory containing the genome folders (default: %(default)s)",
        )
        parser.add_argument(
            "--lst",
            default=None,
            dest="lst_path",
            help="Explicit path to {genome}_unips.lst (overrides --datadir)",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace previously imported UniProt sites on model structures.",
        )

    def handle(self, *args, **options):
        from pathlib import Path

        assembly_name = options["assembly_name"]
        lst_path = options.get("lst_path")
        if lst_path is None:
            datadir = Path(options["datadir"])
            folder_name = mid_shard(assembly_name)
            lst_path = datadir / folder_name / assembly_name / f"{assembly_name}_unips.lst"

        stats = load_uniprot_sites_for_genome(
            assembly_name,
            lst_path,
            dry_run=options["dry_run"],
            overwrite=options["overwrite"],
        )
        if not stats["mapped_accessions"]:
            self.stdout.write(
                self.style.WARNING(f"No UniProt mapping found at {lst_path}; site loading skipped.")
            )
            return

        prefix = "[dry-run] Would map" if options["dry_run"] else "Imported"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} {stats['sites_mapped']} UniProt site(s) across "
                f"{stats['proteins_with_sites']} protein(s), from "
                f"{stats['mapped_accessions']} mapped accession(s)."
            )
        )

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
ft_binding, ft_site) and applies `_persist_uniprot_sites` again, intended
to be run once alphafold/colabfold/structures-chain have completed for the
genome, so the AF/CF BioentryStructure rows actually exist to attach to. It
does not touch EC/GO/PDB annotations (those already ran and are idempotent
regardless).

Experimental (crystal) structures are not covered here or anywhere in this
pass — see functional_annotations.MODEL_STRUCTURE_EXPERIMENTS and its
docstring for why.

Usage
-----
python manage.py load_uniprot_sites GCF_000009045.1 --datadir /app/.../data [--dry-run]
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tpweb.services.functional_annotations import (
    _fetch_uniprot_batch,
    _persist_uniprot_sites,
    _proteome_name,
    _read_uniprot_mapping,
    BATCH_SIZE,
)
from bioseq.models.Bioentry import Bioentry

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

    def handle(self, *args, **options):
        import math
        from pathlib import Path

        assembly_name = options["assembly_name"]
        lst_path = options.get("lst_path")
        if lst_path is None:
            datadir = Path(options["datadir"])
            acclen = len(assembly_name)
            folder_name = assembly_name[math.floor(acclen / 2 - 1):math.floor(acclen / 2 + 2)]
            lst_path = datadir / folder_name / assembly_name / f"{assembly_name}_unips.lst"

        uniprot_mapping = _read_uniprot_mapping(lst_path)
        if not uniprot_mapping:
            raise CommandError(f"No UniProt mapping found at {lst_path}")

        proteome_name = _proteome_name(assembly_name)
        proteins_by_locus = {
            p.accession: p
            for p in Bioentry.objects.filter(biodatabase__name=proteome_name)
        }

        uniprot_accessions = list(uniprot_mapping.keys())
        self.stdout.write(self.style.HTTP_INFO(
            f"{len(uniprot_accessions)} UniProt accession(s) mapped for {assembly_name}."
        ))

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                "[dry-run] Would re-fetch site features and attempt to attach them to "
                "AlphaFold/ColabFold structures. No database changes made."
            ))
            return

        total_sites = 0
        proteins_with_sites = 0
        for i in range(0, len(uniprot_accessions), BATCH_SIZE):
            batch = uniprot_accessions[i:i + BATCH_SIZE]
            entries = _fetch_uniprot_batch(batch)
            with transaction.atomic():
                for entry in entries:
                    locus_tag = uniprot_mapping.get(entry["accession"])
                    if not locus_tag:
                        continue
                    protein = proteins_by_locus.get(locus_tag)
                    if not protein:
                        continue
                    created = _persist_uniprot_sites(protein, entry.get("sites", []))
                    total_sites += created
                    if created:
                        proteins_with_sites += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {total_sites} UniProt site(s) across {proteins_with_sites} protein(s)."
        ))

"""
Backfill BioentryStructure.chain for already-loaded genomes, DB-only.

_update_structure_link() (tpweb/services/experimental_structures.py) used to
truncate a structure's chain field to its first chain letter before saving --
fixed so new links keep every chain xref.chains carries (comma-joined, e.g.
"A,B,C" for a homooligomer or fragmented/heteromeric structure). Existing
BioentryStructure rows saved before that fix still only have one letter.

ExperimentalStructureXref.chains already has the full, untruncated chain list
for every experimental structure -- no re-fetch or re-download needed to fix
this retroactively, just re-deriving BioentryStructure.chain from data
already sitting in the database.
"""

from django.core.management.base import BaseCommand

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure, ExperimentalStructureXref


class Command(BaseCommand):
    help = (
        "Re-derive BioentryStructure.chain from ExperimentalStructureXref.chains "
        "for already-loaded genomes, without re-downloading or re-fetching anything."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "genomes",
            nargs="*",
            help="Genome accession(s) to process. If omitted, runs for all loaded genomes.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        genomes_arg = options["genomes"]

        qs = Biodatabase.objects.exclude(name__endswith=Biodatabase.PROT_POSTFIX)
        if genomes_arg:
            qs = qs.filter(name__in=genomes_arg)

        assemblies = list(qs.values_list("name", flat=True))
        if not assemblies:
            self.stdout.write("No matching genomes found.")
            return

        self.stdout.write(f"Checking structure chains for {len(assemblies)} genome(s).")

        total_updated = 0
        for assembly_name in assemblies:
            proteome_name = f"{assembly_name}{Biodatabase.PROT_POSTFIX}"

            links = BioentryStructure.objects.select_related("bioentry", "pdb").filter(
                bioentry__biodatabase__name=proteome_name, pdb__experiment="EX"
            )
            if not links:
                continue

            xrefs_by_key = {
                (xref.bioentry_id, xref.pdb_id.strip().upper()): xref
                for xref in ExperimentalStructureXref.objects.filter(
                    bioentry__biodatabase__name=proteome_name
                )
            }

            updated = 0
            for link in links:
                xref = xrefs_by_key.get(
                    (link.bioentry_id, str(link.pdb.code or "").strip().upper())
                )
                if xref is None:
                    continue
                full_chain = (xref.chains or "").strip()
                if not full_chain or full_chain == link.chain:
                    continue
                updated += 1
                if not dry_run:
                    link.chain = full_chain
                    link.save(update_fields=["chain"])

            if updated:
                self.stdout.write(
                    f"  [{assembly_name}] {'would update' if dry_run else 'updated'} "
                    f"{updated} structure link(s)."
                )
                total_updated += updated

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(f"\n{verb} {total_updated} structure link(s) in total.")

from django.core.management.base import BaseCommand

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.BioentryDbxref import BioentryDbxref
from bioseq.models.Ontology import Ontology


EC_GO_DBNAMES = (Ontology.EC, "ec", Ontology.GO, "go")


class Command(BaseCommand):
    help = "Remove all EC and GO annotation links from one or all genomes."

    def add_arguments(self, parser):
        parser.add_argument(
            "assembly_name",
            nargs="?",
            default=None,
            help="Genome accession to clear. Omit to clear ALL genomes.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        assembly = options["assembly_name"]
        dry_run = options["dry_run"]

        if assembly:
            proteome_name = f"{assembly}{Biodatabase.PROT_POSTFIX}"
            qs = BioentryDbxref.objects.filter(
                bioentry__biodatabase__name=proteome_name,
                dbxref__dbname__in=EC_GO_DBNAMES,
            )
            label = assembly
        else:
            qs = BioentryDbxref.objects.filter(
                dbxref__dbname__in=EC_GO_DBNAMES,
            )
            label = "ALL genomes"

        count = qs.count()

        if dry_run:
            self.stdout.write(f"[dry-run] Would delete {count} EC/GO links from {label}")
            return

        deleted, details = qs.delete()
        self.stdout.write(f"Deleted {deleted} EC/GO annotation links from {label}")

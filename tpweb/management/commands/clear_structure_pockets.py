from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDBResidueSet


class Command(BaseCommand):
    help = "Delete FPocket/P2Rank pocket residue sets for all structures linked to a genome."

    def add_arguments(self, parser):
        parser.add_argument(
            "genome_name",
            help="Internal genome name in TPW, e.g. public__KpATCC43816.",
        )
        parser.add_argument(
            "--kind",
            choices=("fpocket", "p2rank", "all"),
            default="all",
            help="Pocket type to delete (default: all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many rows would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        genome_name = options["genome_name"]
        proteome_name = genome_name + Biodatabase.PROT_POSTFIX
        if not Biodatabase.objects.filter(name=proteome_name).exists():
            raise CommandError(f"Genome '{genome_name}' is not loaded in TPW.")

        pdb_ids = list(
            BioentryStructure.objects.filter(
                bioentry__biodatabase__name=proteome_name,
            ).values_list("pdb_id", flat=True)
        )
        if not pdb_ids:
            self.stdout.write(f"No structures linked to {genome_name}.")
            return

        residue_set_names = {
            "fpocket": ["FPocketPocket"],
            "p2rank": ["P2RankPocket"],
            "all": ["FPocketPocket", "P2RankPocket"],
        }[options["kind"]]

        qs = PDBResidueSet.objects.filter(
            pdb_id__in=pdb_ids,
            residue_set__name__in=residue_set_names,
        )
        count = qs.count()
        label = ", ".join(residue_set_names)

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] Would delete {count} {label} pocket sets from {genome_name}."
            )
            return

        deleted, _details = qs.delete()
        self.stdout.write(
            f"Deleted {deleted} rows for {count} {label} pocket sets from {genome_name}."
        )

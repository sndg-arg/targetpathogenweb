"""Recompute the Human Targets list summary (structures, ligands, DrugBank,
diseases, pathways, tissue specificity, cell-surface access) from data already
loaded. Run after loading structures, ligands, pathways or expression.

    python manage.py refresh_human_target_summary [--accession P10721 ...]
"""

from django.core.management.base import BaseCommand

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_target_summary import refresh_summaries


class Command(BaseCommand):
    help = "Recompute the per-protein summary behind the Human Targets list columns and filters."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession", nargs="*", default=[], help="Only these UniProt accessions."
        )

    def handle(self, *args, **options):
        queryset = HumanProtein.objects.all()
        if options["accession"]:
            queryset = queryset.filter(uniprot_accession__in=options["accession"])
        done = refresh_summaries(queryset, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(f"Summarized {done} human proteins."))

from django.core.management.base import BaseCommand

from tpweb.services.test_genome_demo import seed_test_genome_demo_annotations


class Command(BaseCommand):
    help = "Seeds deterministic demo EC and experimental-structure annotations for the test genome workspace."

    def add_arguments(self, parser):
        parser.add_argument("assembly_name")

    def handle(self, *args, **options):
        summary = seed_test_genome_demo_annotations(options["assembly_name"])
        self.stdout.write(
            "Seeded demo annotations for "
            f"{summary['assembly_name']}: "
            f"EC links +{summary['ec_links_created']}, "
            f"GO links +{summary['go_links_created']}, "
            f"experimental structures +{summary['experimental_structures_created']}"
        )

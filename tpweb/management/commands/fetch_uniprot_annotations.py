from django.core.management.base import BaseCommand

from tpweb.services.functional_annotations import fetch_and_load_uniprot_annotations


class Command(BaseCommand):
    help = (
        "Fetch real EC and GO annotations from the UniProt REST API "
        "for proteins that have a UniProt mapping."
    )

    def add_arguments(self, parser):
        parser.add_argument("assembly_name", help="Genome accession (e.g. GCF_000009045.1)")
        parser.add_argument(
            "--datadir",
            default="../data",
            help="Base data directory containing the genome folders (default: ../data)",
        )
        parser.add_argument(
            "--lst",
            default=None,
            dest="lst_path",
            help="Explicit path to {genome}_unips.lst (overrides --datadir)",
        )

    def handle(self, *args, **options):
        stats = fetch_and_load_uniprot_annotations(
            assembly_name=options["assembly_name"],
            lst_path=options.get("lst_path"),
            datadir=options["datadir"],
        )
        self.stdout.write(
            f"UniProt annotations for {options['assembly_name']}: "
            f"EC +{stats['ec_created']}, GO +{stats['go_created']}, "
            f"proteins annotated {stats['proteins_annotated']}/{stats['proteins_total']}"
        )

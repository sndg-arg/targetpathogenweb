import os

from django.core.management.base import BaseCommand, CommandError

from tpweb.services.human_offtarget_hits import store_human_offtarget_hits


class Command(BaseCommand):
    help = (
        "Load which human proteins each protein hits from FastTarget's "
        "human_offtarget_blast.tsv (replaces the genome's stored hits)."
    )

    def add_arguments(self, parser):
        parser.add_argument("genome", help="Internal genome (Biodatabase) name, no _prots suffix.")
        parser.add_argument(
            "--blast-file",
            help="Defaults to /app/fasttarget/organism/<genome>/offtarget/human_offtarget_blast.tsv.",
        )

    def handle(self, *args, **options):
        genome = options["genome"]
        path = options["blast_file"] or os.path.join(
            "/app/fasttarget/organism", genome, "offtarget", "human_offtarget_blast.tsv"
        )
        if not os.path.exists(path):
            raise CommandError(f"BLAST file not found: {path}")
        stored = store_human_offtarget_hits(genome, path)
        self.stdout.write(
            self.style.SUCCESS(f"Stored {stored} human off-target hits for {genome}.")
        )

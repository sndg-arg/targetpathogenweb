import gzip
import os
import shutil
import warnings

from Bio import (
    BiopythonDeprecationWarning,
    BiopythonExperimentalWarning,
    BiopythonParserWarning,
    BiopythonWarning,
)
from django.core.management.base import BaseCommand

from bioseq.io.GenebankIO import GenebankIO
from bioseq.io.SeqStore import SeqStore

warnings.simplefilter("ignore", RuntimeWarning)
warnings.simplefilter("ignore", BiopythonWarning)
warnings.simplefilter("ignore", BiopythonParserWarning)
warnings.simplefilter("ignore", BiopythonDeprecationWarning)
warnings.simplefilter("ignore", BiopythonExperimentalWarning)


class Command(BaseCommand):
    help = "Downloads a genebank file from accession number using a custom target accession"

    def add_arguments(self, parser):
        parser.add_argument("--email", default="something@adomain.com")
        parser.add_argument("accession")
        parser.add_argument("--stdout", action="store_true")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--target-accession",
            default=None,
            help="Internal accession used to store the downloaded GBK.",
        )

    def handle(self, *args, **options):
        source_accession = str(options["accession"] or "").strip()
        target_accession = str(options.get("target_accession") or source_accession).strip()
        if not source_accession:
            raise ValueError("A source accession is required.")
        if not target_accession:
            raise ValueError("A target accession is required.")

        h = GenebankIO.get_stream_from_accession(source_accession, options["email"])

        tmp_dir = os.path.join(options["datadir"], "tmp")
        os.makedirs(tmp_dir, exist_ok=True)

        try:
            if options["stdout"]:
                self.stdout.write(h.read())
                return

            tmp_file = os.path.join(tmp_dir, f"{source_accession}.gz")
            with gzip.open(tmp_file, "wt") as hw:
                shutil.copyfileobj(h, hw)

            gbio = GenebankIO(tmp_file)
            gbio.init()

            ss = SeqStore(options["datadir"])
            ss.create_idx_dir(target_accession)
            shutil.move(tmp_file, ss.gbk(target_accession))
        finally:
            h.close()

        self.stderr.write("genome imported!")

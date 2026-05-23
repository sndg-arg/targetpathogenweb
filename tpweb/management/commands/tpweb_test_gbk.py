import gzip
import os
import shutil
import warnings

from Bio import (
    BiopythonDeprecationWarning,
    BiopythonExperimentalWarning,
    BiopythonParserWarning,
    BiopythonWarning,
    SeqIO,
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
    help = "Downloads and truncates the built-in test genome using a custom target accession"

    TEST_ACCESSION = "NZ_AP023069.1"

    def add_arguments(self, parser):
        parser.add_argument("--email", default="something@adomain.com")
        parser.add_argument("--stdout", action="store_true")
        parser.add_argument("--datadir", default="./data")
        parser.add_argument(
            "--target-accession",
            default=self.TEST_ACCESSION,
            help="Internal accession used to store the test GBK.",
        )

    def handle(self, *args, **options):
        target_accession = str(options["target_accession"] or self.TEST_ACCESSION).strip()
        if not target_accession:
            raise ValueError("A target accession is required.")

        h = GenebankIO.get_stream_from_accession(self.TEST_ACCESSION, options["email"])
        try:
            record = next(SeqIO.parse(h, "genbank"))
        finally:
            h.close()

        record.features = record.features[:151]

        ss = SeqStore(options["datadir"])
        ss.create_idx_dir(target_accession)
        test_folder = ss.db_dir(target_accession)

        output_file_path = os.path.join(test_folder, f"{target_accession}.gbk")
        SeqIO.write(record, output_file_path, "genbank")

        with open(output_file_path, "rb") as f_in, gzip.open(f"{output_file_path}.gz", "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        self.stderr.write("genome imported!")

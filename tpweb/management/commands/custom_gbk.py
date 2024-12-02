
import gzip
import io
import shutil
import warnings
import os
from Bio import BiopythonWarning, BiopythonParserWarning, BiopythonDeprecationWarning, BiopythonExperimentalWarning, SeqIO
from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from bioseq.io.GenebankIO import GenebankIO
from bioseq.io.SeqStore import SeqStore

warnings.simplefilter('ignore', RuntimeWarning)
warnings.simplefilter('ignore', BiopythonWarning)
warnings.simplefilter('ignore', BiopythonParserWarning)
warnings.simplefilter('ignore', BiopythonDeprecationWarning)
warnings.simplefilter('ignore', BiopythonExperimentalWarning)


class Command(BaseCommand):
    help = 'Downloads a genebank file from accession number'

    def add_arguments(self, parser):
        parser.add_argument('--email', default="something@adomain.com")
        parser.add_argument('--stdout', action="store_true")
        parser.add_argument('accession')
        parser.add_argument('--custom', default = None)
        parser.add_argument('--datadir', default="./data")

    def handle(self, *args, **options):
        if options["custom"] is None:
            raise ValidationError("Custom option cannot be None.")

        custom_path = options["custom"]

        if not isinstance(custom_path, str):
            raise ValidationError(f"Custom option must be a string, got {type(custom_path)}")

        if not custom_path.endswith(".gbk.gz"):
            raise ValidationError(f"Custom option must end with .gbk.gz, got {custom_path}")

        if not os.path.exists(custom_path):
            raise ValidationError(f"The file {custom_path} does not exist.")

        if not os.access(custom_path, os.R_OK):
            raise ValidationError(f"You don't have read permissions for {custom_path}")

        ss = SeqStore(options["datadir"])
        tmp_file = options["custom"]
        gbio = GenebankIO(tmp_file)
        gbio.init()
        ss.create_idx_dir(gbio.accession)
        print(tmp_file)
        print(ss.gbk(gbio.accession))
        shutil.copy(tmp_file, ss.gbk(gbio.accession))
        self.stderr.write("genome imported!")

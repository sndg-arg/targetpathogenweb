"""Small pure/near-pure helpers from management commands that need a
bioseq fixture (unlike test_management_commands.py's bioseq-free set).
"""

import gzip
import os
import tempfile

from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.management.commands.evaluate_agent import _first_accessions
from tpweb.management.commands.sync_genome_metadata import _open_gbk


class FirstAccessionsTests(TestCase):
    def test_returns_ordered_accessions_limited_to_count(self):
        proteome = Biodatabase.objects.create(name="TEST_prots")
        Bioentry.objects.create(
            biodatabase=proteome, name="protA", accession="LOCUS_A", identifier="LOCUS_A"
        )
        Bioentry.objects.create(
            biodatabase=proteome, name="protB", accession="LOCUS_B", identifier="LOCUS_B"
        )
        Bioentry.objects.create(
            biodatabase=proteome, name="protC", accession="LOCUS_C", identifier="LOCUS_C"
        )

        result = _first_accessions("TEST", 2)

        self.assertEqual(result, ["LOCUS_A", "LOCUS_B"])

    def test_returns_empty_list_for_genome_with_no_proteins(self):
        Biodatabase.objects.create(name="EMPTY_prots")
        self.assertEqual(_first_accessions("EMPTY", 5), [])


class OpenGbkTests(SimpleTestCase):
    def test_uses_gzip_for_gz_suffix(self):
        with tempfile.NamedTemporaryFile(suffix=".gbk.gz", delete=False) as f:
            path = f.name
        try:
            with gzip.open(path, "wt", encoding="utf-8") as gz:
                gz.write("LOCUS test\n")
            with _open_gbk(path) as handle:
                content = handle.read()
            self.assertEqual(content, "LOCUS test\n")
        finally:
            os.unlink(path)

    def test_uses_plain_open_for_non_gz_suffix(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gbk", delete=False, encoding="utf-8"
        ) as f:
            f.write("LOCUS test\n")
            path = f.name
        try:
            with _open_gbk(path) as handle:
                content = handle.read()
            self.assertEqual(content, "LOCUS test\n")
        finally:
            os.unlink(path)

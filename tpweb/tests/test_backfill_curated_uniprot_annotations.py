"""Tests for backfill_curated_uniprot_annotations.py's count/report helpers."""

from io import StringIO

from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from tpweb.management.commands.backfill_curated_uniprot_annotations import (
    _annotation_counts,
    _write_counts,
)


class _FakeCommand:
    def __init__(self):
        self.stdout = StringIO()


class AnnotationCountsTests(TestCase):
    def test_all_counts_zero_for_genome_with_no_dbxrefs(self):
        db = Biodatabase.objects.create(name="TEST_prots")

        counts = _annotation_counts(db)

        self.assertEqual(
            counts,
            {
                "uniprot": 0,
                "ec": 0,
                "go": 0,
                "pdb_xref_proteins": 0,
                "experimental_structure_xrefs": 0,
            },
        )


class WriteCountsTests(SimpleTestCase):
    def test_writes_all_five_labeled_lines(self):
        command = _FakeCommand()
        counts = {
            "uniprot": 1,
            "ec": 2,
            "go": 3,
            "pdb_xref_proteins": 4,
            "experimental_structure_xrefs": 5,
        }

        _write_counts(command, counts)

        output = command.stdout.getvalue()
        self.assertIn("UniProt mapped proteins: 1", output)
        self.assertIn("EC annotated proteins: 2", output)
        self.assertIn("GO annotated proteins: 3", output)
        self.assertIn("Proteins with PDB xrefs: 4", output)
        self.assertIn("Experimental structure xrefs: 5", output)

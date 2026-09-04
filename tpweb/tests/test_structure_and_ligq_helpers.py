"""Tests for a couple of @staticmethod helpers on management Command
classes that don't need self/DB and can be called directly off the class.
"""

import os
import tempfile

from django.test import SimpleTestCase

from tpweb.management.commands.load_af_model import Command as LoadAfModelCommand
from tpweb.management.commands.load_ligq_2_results import Command as LoadLigqResultsCommand


class SanitizeCifTests(SimpleTestCase):
    def test_returns_original_path_when_no_apostrophe(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", delete=False, encoding="utf-8"
        ) as f:
            f.write("_chem_comp.name  ADENOSINE-TRIPHOSPHATE\n")
            path = f.name
        try:
            result = LoadAfModelCommand._sanitize_cif(path)
            self.assertEqual(result, path)
        finally:
            os.unlink(path)

    def test_replaces_apostrophes_in_a_new_temp_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", delete=False, encoding="utf-8"
        ) as f:
            f.write('_chem_comp.name  "ADENOSINE-5\'-TRIPHOSPHATE"\n')
            path = f.name
        result = None
        try:
            result = LoadAfModelCommand._sanitize_cif(path)
            self.assertNotEqual(result, path)
            with open(result, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("'", content)
            self.assertIn("*", content)
        finally:
            os.unlink(path)
            if result and result != path:
                os.unlink(result)


class FormatKnownNotesTests(SimpleTestCase):
    def test_joins_present_fields_and_skips_blank_ones(self):
        row = {
            "search_type": "direct",
            "source": "ChEMBL",
            "mechanism": "",
            "activity_comment": None,
            "curation_method": "manual",
            "binding_sites": "",
        }

        self.assertEqual(
            LoadLigqResultsCommand._format_known_notes(row),
            "LigQ direct | source=ChEMBL | curation=manual",
        )

    def test_empty_row_returns_empty_string(self):
        self.assertEqual(LoadLigqResultsCommand._format_known_notes({}), "")


class FormatZincNotesTests(SimpleTestCase):
    def test_joins_present_fields(self):
        row = {"search_type": "similarity", "query_id": "Q1", "sseqid": "P12345"}

        self.assertEqual(
            LoadLigqResultsCommand._format_zinc_notes(row),
            "LigQ similarity | query=Q1 | homolog=P12345",
        )

    def test_empty_row_returns_empty_string(self):
        self.assertEqual(LoadLigqResultsCommand._format_zinc_notes({}), "")

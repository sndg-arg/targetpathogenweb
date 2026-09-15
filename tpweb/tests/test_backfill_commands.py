"""Tests for the selected-structure backfill commands' pure helpers.

load_selected_pdb_backfill.py and load_selected_alphafold_backfill.py both
carry a near-identical clean/is_pdb_code/folder_path/parse_structure_candidates
set copy-pasted from the export_selected_* commands (already covered in
test_management_commands.py) -- per tpw-django-patterns's "before
deduplicating a copy-pasted helper, grep every call site first" note, this
file exists to pin down the one genuine behavioral difference found: this
module's _parse_structure_candidates does NOT dedupe/sort like the export
variant does.
"""

import os
import tempfile

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from tpweb.management.commands.load_selected_pdb_backfill import (
    _clean as pdb_backfill_clean,
    _folder_path as pdb_backfill_folder_path,
    _is_pdb_code as pdb_backfill_is_pdb_code,
    _parse_structure_candidates,
)
from tpweb.management.commands._shared import read_manifest
from tpweb.management.commands.load_selected_alphafold_backfill import (
    as_bool,
    clean as af_backfill_clean,
    default_manifest,
    default_model_dir,
    folder_path as af_backfill_folder_path,
    structure_code,
)


class LoadSelectedPdbBackfillHelperTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(pdb_backfill_clean(None), "")
        self.assertEqual(pdb_backfill_clean("null"), "")
        self.assertEqual(pdb_backfill_clean("  1abc  "), "1abc")

    def test_is_pdb_code_requires_length_four_alnum(self):
        self.assertTrue(pdb_backfill_is_pdb_code("1ABC"))
        self.assertFalse(pdb_backfill_is_pdb_code("AB"))

    def test_folder_path_splits_genome_accession_into_middle_bucket_directory(self):
        self.assertEqual(
            pdb_backfill_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )

    def test_parse_structure_candidates_preserves_order_and_duplicates(self):
        # Unlike export_selected_pdb_pocket_jobs._parse_structure_candidates
        # (sorted(set(...))), this variant is a plain list comprehension --
        # order-preserving and duplicate-preserving. A *set*-literal input
        # would hide that (Python's set literal itself dedupes before this
        # function ever runs), so this uses a list literal, which preserves
        # both order and the duplicate through ast.literal_eval.
        candidates = _parse_structure_candidates("['2XYZ', '1ABC', '1ABC']")
        self.assertEqual(candidates, ["2XYZ", "1ABC", "1ABC"])


class LoadSelectedAlphafoldBackfillHelperTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(af_backfill_clean(None), "")
        self.assertEqual(af_backfill_clean("nan"), "")

    def test_as_bool_recognizes_truthy_spellings(self):
        self.assertTrue(as_bool("true"))
        self.assertTrue(as_bool("Yes"))
        self.assertTrue(as_bool("1"))
        self.assertFalse(as_bool("0"))
        self.assertFalse(as_bool(""))

    def test_structure_code_uppercases_and_prefixes(self):
        self.assertEqual(structure_code("p12345"), "AF_P12345")

    def test_folder_path_splits_genome_accession_into_middle_bucket_directory(self):
        self.assertEqual(
            af_backfill_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )

    def test_default_manifest_and_model_dir_nest_under_selected_alphafold_jobs(self):
        manifest = default_manifest("/app/tp/data", "NZ_AP023069.1")
        model_dir = default_model_dir("/app/tp/data", "NZ_AP023069.1")

        self.assertEqual(
            manifest,
            "/app/tp/data/023/NZ_AP023069.1/selected_alphafold_jobs/"
            "NZ_AP023069.1_selected_alphafold.tsv",
        )
        self.assertEqual(model_dir, "/app/tp/data/023/NZ_AP023069.1/selected_alphafold_jobs/models")


class ReadManifestTests(SimpleTestCase):
    def test_raises_command_error_when_file_missing(self):
        with self.assertRaises(CommandError):
            read_manifest("/does/not/exist.tsv")

    def test_reads_tab_delimited_rows_as_dicts(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".tsv", delete=False, encoding="utf-8"
        ) as f:
            f.write("accession\tpdb_code\nP12345\t1ABC\n")
            path = f.name
        try:
            rows = read_manifest(path)
        finally:
            os.unlink(path)

        self.assertEqual(rows, [{"accession": "P12345", "pdb_code": "1ABC"}])

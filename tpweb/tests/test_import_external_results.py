"""Tests for import_external_results.py's pure helpers -- the Gates-Targets
import path documented in CLAUDE.md's "Importing external analysis results"
section. Zero coverage before this: _compute_folder_path shares the same
bucket-arithmetic bug class documented across pipeline/tests (an earlier
off-by-one in a sibling copy of this exact function was only caught by a
real cluster run, not by inspection), and _gates_property_pockets/
_counts_to_hit_no_hit are the parsers that decide what pocket data and
hit/no-hit scores actually get imported.
"""

import os
import tempfile

from django.test import SimpleTestCase

from tpweb.management.commands.import_external_results import (
    _boltz_model_path,
    _compute_folder_path,
    _counts_to_hit_no_hit,
    _gates_property_pockets,
)
from tpweb.services.structure_sources import (
    PDB_MODEL_EXPERIMENTS,
    STRUCTURE_SOURCE_BOLTZ,
    classify_structure_experiment,
)


class BoltzModelPathTests(SimpleTestCase):
    def test_finds_top1_cif(self):
        with tempfile.TemporaryDirectory() as prot_dir:
            os.makedirs(os.path.join(prot_dir, "boltz_top1"))
            path = os.path.join(prot_dir, "boltz_top1", "BOLTZ_FQU82_00002.cif")
            open(path, "w").close()

            self.assertEqual(_boltz_model_path(prot_dir, "FQU82_00002"), path)

    def test_missing_model_returns_none(self):
        with tempfile.TemporaryDirectory() as prot_dir:
            self.assertIsNone(_boltz_model_path(prot_dir, "FQU82_00002"))

    def test_boltz_is_a_predicted_model_not_experimental(self):
        self.assertIn("BZ", PDB_MODEL_EXPERIMENTS)
        self.assertEqual(classify_structure_experiment("BZ"), STRUCTURE_SOURCE_BOLTZ)


class ComputeFolderPathTests(SimpleTestCase):
    def test_splits_genome_accession_into_middle_bucket_directory(self):
        self.assertEqual(
            _compute_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )


class GatesPropertyPocketsTests(SimpleTestCase):
    def test_reads_pockets_from_cb_prefixed_dict(self):
        raw = {"CB_LOCUS1": {"p1": {"number": 1, "properties": {"druggability": 0.8}}}}

        result = _gates_property_pockets("LOCUS1", raw)

        self.assertEqual(
            result,
            [{"number": 1, "as_lines": [], "atoms": [], "properties": {"druggability": 0.8}}],
        )

    def test_reads_pockets_from_bare_locus_tag_list_using_id_as_number(self):
        raw = {
            "LOCUS1": [
                {"id": "P1", "properties": {"score": 5}},
                {"id": "P2", "properties": {"score": 3}},
            ]
        }

        result = _gates_property_pockets("LOCUS1", raw)

        self.assertEqual([entry["number"] for entry in result], ["P1", "P2"])

    def test_falls_back_to_raw_itself_when_no_matching_key(self):
        raw = {"other_key": {"number": 1, "properties": {"score": 1}}}

        result = _gates_property_pockets("LOCUS1", raw)

        self.assertEqual(
            result, [{"number": 1, "as_lines": [], "atoms": [], "properties": {"score": 1}}]
        )

    def test_skips_non_dict_entries(self):
        raw = {
            "LOCUS1": [
                {"number": 1, "properties": {"x": 1}},
                "not-a-dict",
                {"number": 2, "properties": {"x": 2}},
            ]
        }

        result = _gates_property_pockets("LOCUS1", raw)

        self.assertEqual([entry["number"] for entry in result], [1, 2])

    def test_properties_falls_back_to_whole_pocket_dict_when_no_properties_key(self):
        raw = {"LOCUS1": [{"number": 5, "druggability": 0.9}]}

        result = _gates_property_pockets("LOCUS1", raw)

        self.assertEqual(result[0]["properties"], {"number": 5, "druggability": 0.9})


class CountsToHitNoHitTests(SimpleTestCase):
    def test_missing_value_is_no_hit(self):
        self.assertEqual(_counts_to_hit_no_hit(None), "no_hit")

    def test_positive_number_is_hit(self):
        self.assertEqual(_counts_to_hit_no_hit(5), "hit")

    def test_zero_is_no_hit(self):
        self.assertEqual(_counts_to_hit_no_hit(0), "no_hit")

    def test_numeric_string_is_evaluated_numerically(self):
        self.assertEqual(_counts_to_hit_no_hit("3"), "hit")

    def test_non_numeric_text_falls_back_to_hit(self):
        self.assertEqual(_counts_to_hit_no_hit("abc"), "hit")

    def test_no_hit_text_is_recognized(self):
        self.assertEqual(_counts_to_hit_no_hit("no_hit"), "no_hit")

    def test_empty_string_is_no_hit(self):
        self.assertEqual(_counts_to_hit_no_hit(""), "no_hit")

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tpweb.management.commands.protein_column_coverage import has_score_data, score_presence


class ProteinColumnCoverageTests(TestCase):
    def test_fixed_coverage_uses_canonical_go_namespace(self):
        from tpweb.management.commands.protein_column_coverage import fixed_presence
        from tpweb.services.protein_annotations import ANNOTATION_KIND_CONFIG

        row = SimpleNamespace(dbxref=SimpleNamespace(dbname="GeneOntology", accession="GO:0016020"))
        protein = SimpleNamespace(
            accession="TEST",
            description="Test",
            genes=lambda: [],
            structures=SimpleNamespace(all=lambda: []),
            dbxrefs=SimpleNamespace(all=lambda: [row]),
            metabolic_reaction_count=0,
        )
        with patch.dict(ANNOTATION_KIND_CONFIG["go"], {"dbnames": ["GeneOntology", "go"]}):
            self.assertTrue(fixed_presence(protein)["GO"])

    def row(self, kind="N", value="", numeric_value=None, protein_id=1, param_id=3):
        return SimpleNamespace(
            score_param=SimpleNamespace(type=kind),
            score_param_id=param_id,
            value=value,
            numeric_value=numeric_value,
            bioentry_id=protein_id,
        )

    def test_zero_and_false_are_data(self):
        self.assertTrue(has_score_data(self.row(numeric_value=0)))
        self.assertTrue(has_score_data(self.row(kind="C", value=False)))
        self.assertTrue(has_score_data(self.row(kind="C", value="False")))

    def test_empty_placeholders_are_not_data(self):
        for value in [None, "", " ", "None", "null", "nan", "-", "—", "<NA>"]:
            with self.subTest(value=value):
                self.assertFalse(has_score_data(self.row(kind="C", value=value)))

    def test_invalid_or_nonfinite_numeric_values_are_not_data(self):
        for value in ["bad", "nan", "inf", "-inf", ""]:
            with self.subTest(value=value):
                self.assertFalse(has_score_data(self.row(value=value)))

    def test_numeric_text_and_decimal_comma_are_accepted(self):
        self.assertTrue(has_score_data(self.row(value="0")))
        self.assertTrue(has_score_data(self.row(value="0,25")))

    def test_count_distinguishes_shared_values_and_counts_each_column_once(self):
        rows = [
            self.row(numeric_value=0),
            self.row(numeric_value=1),
            self.row(numeric_value=2, protein_id=2, param_id=4),
            self.row(numeric_value=3, param_id=99),
        ]
        protein = SimpleNamespace(pk=1, score_params=SimpleNamespace(all=lambda: rows))
        self.assertEqual(score_presence(protein, {3, 4, 5}), ({3, 4}, {4}))

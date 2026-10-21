import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "repair", Path(__file__).with_name("repair_softcore_columns.py")
)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class BooleanRepairTests(unittest.TestCase):
    def test_converts_existing_numeric_and_boolean_encodings(self):
        for raw in ("1", "1.0", "True", "true", 1, True):
            self.assertEqual(repair.boolean_text(raw), "True")
        for raw in ("0", "0.0", "False", "false", 0, False):
            self.assertEqual(repair.boolean_text(raw), "False")

    def test_missing_data_remains_missing(self):
        for raw in (None, "", "nan"):
            self.assertEqual(repair.boolean_text(raw), "")

    def test_uses_numeric_value_if_text_is_empty(self):
        self.assertEqual(repair.boolean_text("", 0), "False")
        self.assertEqual(repair.boolean_text("", 1), "True")

    def test_rejects_scores_outside_boolean_range(self):
        with self.assertRaises(ValueError):
            repair.boolean_text("0.5")

import importlib.util
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch


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


class MergeAliasTests(unittest.TestCase):
    def setUp(self):
        self.values = Mock()
        self.shares = Mock()
        self.models = patch.dict(
            sys.modules,
            {
                "tpweb.models.ScoreParamValue": SimpleNamespace(
                    ScoreParamValue=SimpleNamespace(objects=self.values)
                ),
                "tpweb.models.CustomParamShare": SimpleNamespace(
                    CustomParamShare=SimpleNamespace(objects=self.shares)
                ),
            },
        )
        self.models.start()
        self.addCleanup(self.models.stop)
        self.source = SimpleNamespace(
            name="softcore_roary", description="", save=Mock(), delete=Mock()
        )
        self.target = SimpleNamespace(name="soft_core_roary", description="", save=Mock())

    def test_rename_without_target_keeps_existing_parameter(self):
        repair.merge_aliases([self.source])
        self.assertEqual(self.source.name, "soft_core_roary")
        self.source.save.assert_called_once_with(update_fields=["name"])
        self.source.delete.assert_not_called()
        self.values.filter.assert_not_called()

    def test_disagreement_is_rejected_before_moving_rows(self):
        current = Mock()
        current.values_list.return_value = [(42, "True")]
        self.values.filter.side_effect = [current, [SimpleNamespace(bioentry_id=42, value="False")]]
        with self.assertRaisesRegex(RuntimeError, "Conflicting soft-core values"):
            repair.merge_aliases([self.source, self.target])
        self.source.delete.assert_not_called()
        self.shares.filter.assert_not_called()

    def test_conflicting_visibility_is_rejected(self):
        current = Mock()
        current.values_list.return_value = []
        self.values.filter.side_effect = [current, []]
        share = SimpleNamespace(genome_name="genome", visibility="project")
        target_share = Mock()
        target_share.first.return_value = SimpleNamespace(visibility="public")
        self.shares.filter.side_effect = [[share], target_share]
        with self.assertRaisesRegex(RuntimeError, "Conflicting sharing"):
            repair.merge_aliases([self.source, self.target])
        self.source.delete.assert_not_called()

    def test_move_preserves_values_and_share_visibility(self):
        current = Mock()
        current.values_list.return_value = []
        overlaps = Mock()
        move = Mock()
        move.update.return_value = 5322
        self.values.filter.side_effect = [
            current,
            [SimpleNamespace(bioentry_id=42, value="False")],
            overlaps,
            move,
        ]
        share = SimpleNamespace(genome_name="genome", visibility="project", save=Mock())
        target_share = Mock()
        target_share.first.return_value = None
        self.shares.filter.side_effect = [[share], target_share]
        repair.merge_aliases([self.source, self.target])
        move.update.assert_called_once_with(score_param=self.target)
        self.assertIs(share.score_param, self.target)
        self.assertEqual(share.visibility, "project")
        share.save.assert_called_once_with(update_fields=["score_param"])
        self.source.delete.assert_called_once()

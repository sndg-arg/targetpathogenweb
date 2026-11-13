import unittest

from django.core.management.base import CommandError
from tpweb.management.commands.load_identical_sequence_groups import _table_members
from tpweb.management.commands.backfill_identical_sequence_links import (
    _validate_group_sequences,
    _sequence_group_index,
)


HEADER = ["id_representativo", "identicos_en_otras_cepas"]


class IdenticalSequenceImportTests(unittest.TestCase):
    def test_sequence_index_excludes_inconsistent_table_groups(self):
        index = _sequence_group_index([(1, "MAU"), (1, "MAX"), (2, "MAC"), (2, "MAC")])
        self.assertEqual(index, {"MAC": {2}})

    def test_sequence_index_does_not_choose_between_duplicate_groups(self):
        self.assertEqual(_sequence_group_index([(1, "MAU"), (2, "MAU")]), {"MAU": {1, 2}})

    def test_actual_two_column_format(self):
        groups, skipped = _table_members(
            [
                HEADER,
                ["MO417_00005 (WHR12791.1)", "KP13: KP13_07341 (ANJ86556.1)"],
                ["MO417_00010 (WHR12792.1)", "-"],
            ]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual([m["strain_label"] for m in groups[0]], ["ST11_VA569", "KP13"])

    def test_representatives_can_belong_to_other_strains(self):
        groups, _ = _table_members(
            [
                HEADER,
                ["KP13_00057 (AHE41981.1)", "ATCC43816: VK055_3368 (AIK81925.1)"],
            ],
            "ST11_VA569",
        )
        self.assertEqual(groups[0][0]["strain_label"], "KP13")

    def test_va569_label_is_canonicalized(self):
        groups, _ = _table_members([HEADER, ["VK055_0001", "VA569: MO417_00001"]])
        self.assertEqual(groups[0][0]["strain_label"], "ATCC43816")
        self.assertEqual(groups[0][1]["strain_label"], "ST11_VA569")

    def test_legacy_leading_id_column(self):
        groups, _ = _table_members([["id", *HEADER], ["1", "MO417_1", "KP13: KP13_1"]])
        self.assertEqual(groups[0][0]["locus_tag"], "MO417_1")

    def test_wrong_header_does_not_silently_import_zero_groups(self):
        with self.assertRaises(CommandError):
            _table_members([["wrong", "header"], ["MO417_1", "KP13: KP13_1"]])

    def test_repeated_member_is_rejected(self):
        with self.assertRaises(CommandError):
            _table_members([HEADER, ["MO417_1", "KP13: KP13_1"], ["MO417_2", "KP13: KP13_1"]])

    def test_mislabeled_match_is_rejected(self):
        with self.assertRaises(CommandError):
            _table_members([HEADER, ["MO417_1", "KP13: VK055_1"]])

    def test_sequence_mismatch_prevents_backfill(self):
        with self.assertRaises(CommandError):
            _validate_group_sequences({1: {"MAU", "MAX"}}, "KP13")

    def test_empty_sequence_prevents_backfill(self):
        with self.assertRaises(CommandError):
            _validate_group_sequences({1: {""}}, "KP13")

    def test_equal_sequences_pass(self):
        _validate_group_sequences({1: {"MAU"}}, "KP13")

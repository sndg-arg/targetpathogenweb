import json
import tempfile
import unittest
from pathlib import Path

from human_target.services.human_coverage_audit import (
    compare_pdb_pairs,
    expected_pdb_pairs,
    reference_inventory,
)


class HumanCoverageAuditTests(unittest.TestCase):
    def test_deprecated_links_are_distinguished_from_absent_links(self):
        result = compare_pdb_pairs(
            {("P1", "9LSJ"), ("P2", "3JPN")},
            {("P1", "9LSJ"), ("P2", "3JPN")},
            set(),
            deprecated_linked={("P1", "9LSJ")},
        )
        self.assertEqual(result["deprecated_only_pairs"], 1)
        self.assertEqual(result["without_any_structure_link"], 1)
        self.assertEqual(result["complete_pairs"], 0)

    def test_normalizes_and_deduplicates_expected_pairs(self):
        rows = [
            (
                "P1",
                [
                    {"database": "PDB", "id": " 1abc "},
                    {"database": "PDB", "id": "1ABC"},
                    {"database": "PDB", "id": " "},
                    {"database": "PDB"},
                    {"database": "Other", "id": "2ABC"},
                ],
            ),
            ("P2", None),
        ]
        self.assertEqual(expected_pdb_pairs(rows), {("P1", "1ABC")})

    def test_xref_and_link_are_both_required(self):
        expected = {("P1", "1ABC"), ("P2", "1ABC"), ("P3", "2ABC")}
        result = compare_pdb_pairs(
            expected, {("P1", "1ABC"), ("P2", "1ABC")}, {("P1", "1ABC"), ("P3", "2ABC")}
        )
        self.assertEqual(result["complete_pairs"], 1)
        self.assertEqual(result["pending_pairs"], 2)
        self.assertEqual(result["xref_without_structure_link"], 1)
        self.assertEqual(result["structure_link_without_xref"], 1)
        self.assertEqual(result["pending_distinct_pdb"], 2)

    def test_unrelated_records_do_not_inflate_coverage(self):
        result = compare_pdb_pairs({("P1", "1ABC")}, {("P9", "9XYZ")}, {("P9", "9XYZ")})
        self.assertEqual(result["complete_percent"], 0)
        self.assertEqual(result["extra_registered_pairs"], 1)

    def test_empty_expected_has_no_percentage(self):
        self.assertIsNone(compare_pdb_pairs(set(), set(), set())["complete_percent"])

    def test_samples_are_bounded_without_changing_totals(self):
        expected = {("P2", "1ABC"), ("P1", "1ABC")}
        result = compare_pdb_pairs(expected, set(), set(), sample_size=1)
        self.assertEqual(result["pending_sample"], [["P1", "1ABC"]])
        self.assertEqual(result["pending_distinct_pdb"], 1)
        self.assertEqual(result["pending_pairs"], 2)

    def test_reference_inventory_counts_rows_not_files_and_handles_absences(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "P1"
            folder.mkdir()
            (folder / "P1_full.json").write_text(json.dumps({"sequence": {"value": "MKT"}}))
            ligq = folder / "ligq" / "search_results" / "P1"
            ligq.mkdir(parents=True)
            (ligq / "known_ligands.tsv").write_text("id\tname\n1\ta\n2\tb\n")
            result = reference_inventory(tmp)["P1"]
            self.assertEqual(result["sequence"], "MKT")
            self.assertEqual(result["ligand_tables"]["known_ligands.tsv"], {"files": 1, "rows": 2})
            self.assertEqual(
                result["ligand_tables"]["predicted_ligands.tsv"], {"files": 0, "rows": 0}
            )
            self.assertFalse(result["reactions_file"])
            self.assertEqual(result["structure_files"]["AlphaFill"], 0)

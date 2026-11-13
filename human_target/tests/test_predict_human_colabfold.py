import unittest

from human_target.management.commands.predict_human_colabfold import select_candidates


class SelectCandidatesTests(unittest.TestCase):
    def test_selenocysteine_sent_as_cysteine(self):
        selected, skipped = select_candidates([("P1", "MKU" * 20)], 30, 2500)
        self.assertEqual(selected, [("P1", "MKC" * 20)])
        self.assertEqual(skipped, [])

    def test_skips_fragments_giants_and_unknown_residues(self):
        rows = [("J1", "M" * 12), ("BIG", "M" * 3515), ("X1", "MX" * 20)]
        selected, skipped = select_candidates(rows, 30, 2500)
        self.assertEqual(selected, [])
        self.assertEqual([accession for accession, _ in skipped], ["J1", "BIG", "X1"])

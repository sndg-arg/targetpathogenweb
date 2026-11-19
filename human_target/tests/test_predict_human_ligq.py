import tempfile
import unittest
from pathlib import Path

from human_target.management.commands.predict_human_ligq import fasta_accessions, plan_new_chunks


class PlanNewChunksTests(unittest.TestCase):
    def test_skips_assigned_and_excluded_and_chunks_the_rest(self):
        rows = [("A", "MK"), ("B", "MU"), ("C", "MK"), ("D", "MK"), ("E", "")]
        chunks = plan_new_chunks(rows, assigned=["A"], chunk_size=2, excluded=("D",))
        self.assertEqual(chunks, [[("B", "MC"), ("C", "MK")]])

    def test_reads_accessions_back_from_chunk_fasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proteins.fasta"
            path.write_text(">P1\nMK\n>P2 extra\nMK\n", encoding="utf-8")
            self.assertEqual(fasta_accessions(path), ["P1", "P2"])

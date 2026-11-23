import os
import tempfile

from django.test import SimpleTestCase

from tpweb.services.human_offtarget_hits import parse_blast_hits, parse_subject_id


class HumanOfftargetHitParsingTests(SimpleTestCase):
    def test_parse_subject_id(self):
        self.assertEqual(parse_subject_id("sp|P29401|TKT_HUMAN"), ("P29401", "TKT_HUMAN"))
        self.assertEqual(parse_subject_id("P29401"), ("P29401", ""))

    def test_best_hsp_per_human_protein_sorted_by_bitscore(self):
        rows = [
            "g1\tsp|P1|A_HUMAN\t30.0\t100\t0\t0\t1\t100\t5\t104\t1e-10\t50\t80\t80",
            "g1\tsp|P1|A_HUMAN\t25.0\t60\t0\t0\t1\t60\t5\t64\t1e-6\t30\t50\t80",
            "g1\tsp|P2|B_HUMAN\t40.0\t120\t0\t0\t1\t120\t1\t120\t1e-20\t90\t95\t95",
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as handle:
            handle.write("\n".join(rows) + "\n")
        try:
            hits = parse_blast_hits(handle.name)
        finally:
            os.unlink(handle.name)

        self.assertEqual([hit["human_accession"] for hit in hits["g1"]], ["P2", "P1"])
        self.assertEqual(hits["g1"][1]["bitscore"], 50.0)
        self.assertEqual(hits["g1"][0]["query_coverage"], 95.0)

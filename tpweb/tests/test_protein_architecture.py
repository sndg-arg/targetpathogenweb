from django.test import SimpleTestCase

from tpweb.services.protein_architecture import (
    build_interpro_architecture,
    coverage_cells,
    format_sequence,
)


class InterproArchitectureTests(SimpleTestCase):
    def test_pfam_draws_domains_and_the_rest_become_rows(self):
        features = [
            {
                "start": 1,
                "end": 22,
                "db": "SignalP_GRAM_NEGATIVE",
                "term": "SignalP-noTM",
                "name": "",
            },
            {"start": 30, "end": 200, "db": "Pfam", "term": "PF00001", "name": "7tm"},
            {"start": 10, "end": 300, "db": "PANTHER", "term": "PTHR1", "name": "family"},
            {"start": 40, "end": 60, "db": "Phobius", "term": "TRANSMEMBRANE", "name": ""},
            {"start": 61, "end": 90, "db": "Phobius", "term": "CYTOPLASMIC_DOMAIN", "name": ""},
            {"start": 250, "end": 280, "db": "MobiDBLite", "term": "mobidb-lite", "name": ""},
        ]
        arch = build_interpro_architecture(features, 300)
        self.assertEqual(arch["domain_source"], "Pfam")
        self.assertEqual([d["description"] for d in arch["domains"]], ["7tm"])
        self.assertEqual([t["kind"] for t in arch["topology"]], ["membrane", "inside"])
        self.assertEqual(len(arch["signal"]), 1)
        # Other signatures (PANTHER here) stay in the feature table, off the map.
        self.assertEqual([row["key"] for row in arch["tick_rows"]], ["disorder"])

    def test_no_features_no_map(self):
        self.assertIsNone(build_interpro_architecture([], 300))
        self.assertIsNone(build_interpro_architecture([{"start": 1, "end": 5, "db": "Pfam"}], 0))

    def test_coverage_counts_structures_per_stretch(self):
        coverage = coverage_cells([(1, 150), (100, 300)], 300, bins=6)
        self.assertEqual([cell["count"] for cell in coverage["cells"]], [1, 2, 2, 1, 1, 1])
        self.assertIsNone(coverage_cells([(None, None)], 300))

    def test_sequence_lines(self):
        lines = format_sequence("A" * 65)
        self.assertEqual([line["start"] for line in lines], [1, 61])
        self.assertEqual(lines[1]["blocks"], [{"start": 61, "text": "AAAAA"}])

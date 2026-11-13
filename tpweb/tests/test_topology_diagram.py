from django.test import SimpleTestCase

from tpweb.services.topology_diagram import build_topology_diagram


class TopologyDiagramTests(SimpleTestCase):
    def test_helices_merge_and_termini_alternate_sides(self):
        segments = [
            {"start": 1, "end": 20, "kind": "outside"},
            {"start": 21, "end": 43, "kind": "membrane"},
            {"start": 22, "end": 44, "kind": "membrane"},  # same helix, second predictor
            {"start": 70, "end": 92, "kind": "membrane"},
        ]
        topo = build_topology_diagram(segments, 120, "Periplasm", "Cytoplasm")
        self.assertEqual(topo["count"], 2)
        self.assertEqual((topo["n_side"], topo["c_side"]), ("outside", "outside"))
        self.assertIsNone(topo["n_domain"])

    def test_long_terminal_region_draws_as_a_domain(self):
        segments = [
            {"start": 1, "end": 520, "kind": "outside"},
            {"start": 521, "end": 543, "kind": "membrane"},
        ]
        topo = build_topology_diagram(segments, 976, "Extracellular", "Cytoplasm")
        self.assertEqual(topo["n_domain"]["residues"], 520)
        self.assertEqual(topo["c_domain"]["residues"], 433)
        self.assertEqual(topo["c_side"], "inside")

    def test_no_transmembrane_segment_no_diagram(self):
        self.assertIsNone(
            build_topology_diagram([{"start": 1, "end": 9, "kind": "inside"}], 9, "a", "b")
        )

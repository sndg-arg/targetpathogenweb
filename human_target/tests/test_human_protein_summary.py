from django.test import SimpleTestCase

from human_target.services.human_protein_summary import build_human_xref_context


class _FakeHumanProtein:
    def __init__(self, cross_references_raw):
        self.cross_references_raw = cross_references_raw


class BuildHumanXrefContextTests(SimpleTestCase):
    def test_go_entries_are_excluded_since_function_tab_shows_them_better(self):
        xrefs = [
            {"database": "GO", "id": "GO:0005886"},
            {"database": "PDB", "id": "1ABC"},
        ]
        context = build_human_xref_context(_FakeHumanProtein(xrefs))

        labels = [group["label"] for group in context["groups"]]
        self.assertNotIn("Other", labels)
        structure_group = next(g for g in context["groups"] if g["label"] == "Structure")
        self.assertEqual(structure_group["items"], [{"database": "PDB", "id": "1ABC"}])

    def test_unmapped_non_go_database_falls_into_other(self):
        xrefs = [{"database": "SomeObscureDB", "id": "X1"}]
        context = build_human_xref_context(_FakeHumanProtein(xrefs))

        other_group = next(g for g in context["groups"] if g["label"] == "Other")
        self.assertEqual(other_group["items"], [{"database": "SomeObscureDB", "id": "X1"}])


class HumanArchitectureTests(SimpleTestCase):
    def test_places_features_on_rows_as_percent_of_the_sequence(self):
        from human_target.services.human_protein_summary import build_human_architecture

        features = [
            {"type": "Signal", "start": 1, "end": 25},
            {"type": "Topological domain", "start": 26, "end": 50, "description": "Extracellular"},
            {"type": "Transmembrane", "start": 51, "end": 70},
            {"type": "Topological domain", "start": 71, "end": 100, "description": "Cytoplasmic"},
            {"type": "Domain", "start": 30, "end": 45, "description": "Ig-like"},
            {"type": "Binding site", "start": 80, "end": 80},
            {"type": "Natural variant", "start": 90, "end": 90},
            {"type": "Chain", "start": 26, "end": 100},
        ]
        arch = build_human_architecture(features, 100)
        self.assertEqual([t["kind"] for t in arch["topology"]], ["outside", "membrane", "inside"])
        self.assertEqual(arch["domains"][0]["left"], 29)
        self.assertEqual(arch["domains"][0]["width"], 16)
        self.assertEqual([row["key"] for row in arch["tick_rows"]], ["sites", "variants"])
        self.assertEqual([tick["position"] for tick in arch["ruler"]], list(range(10, 100, 10)))

    def test_no_map_without_length_or_drawable_features(self):
        from human_target.services.human_protein_summary import build_human_architecture

        self.assertIsNone(build_human_architecture([{"type": "Domain", "start": 1}], 0))
        self.assertIsNone(build_human_architecture([{"type": "Chain", "start": 1, "end": 9}], 9))

    def test_sequence_lines_of_sixty_in_blocks_of_ten(self):
        from human_target.services.human_protein_summary import format_sequence

        lines = format_sequence("A" * 65)
        self.assertEqual([line["start"] for line in lines], [1, 61])
        self.assertEqual([block["start"] for block in lines[0]["blocks"]], [1, 11, 21, 31, 41, 51])
        self.assertEqual(lines[1]["blocks"], [{"start": 61, "text": "AAAAA"}])


class StripCitationsTests(SimpleTestCase):
    def test_pubmed_lists_go_and_other_parentheticals_stay(self):
        from human_target.services.human_protein_summary import strip_citations

        self.assertEqual(
            strip_citations(
                "Acts (PubMed:1, PubMed:2). Binds (By similarity). Z (PubMed:3, By similarity)."
            ),
            "Acts. Binds (By similarity). Z (By similarity).",
        )

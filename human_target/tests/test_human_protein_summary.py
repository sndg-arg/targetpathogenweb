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

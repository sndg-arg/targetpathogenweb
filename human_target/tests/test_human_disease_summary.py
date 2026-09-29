from django.test import SimpleTestCase

from human_target.services.human_disease_summary import build_human_disease_context


class _FakeHumanProtein:
    def __init__(self, disease_comments):
        self.disease_comments = disease_comments


class BuildHumanDiseaseContextTests(SimpleTestCase):
    def test_reports_no_diseases_for_empty_list(self):
        context = build_human_disease_context(_FakeHumanProtein([]))
        self.assertEqual(context, {"diseases": [], "has_diseases": False})

    def test_passes_through_disease_comments_as_is(self):
        diseases = [
            {"name": "Disease A", "acronym": "DA", "description": "desc", "mim": "MIM:12345"}
        ]
        context = build_human_disease_context(_FakeHumanProtein(diseases))
        self.assertEqual(context["diseases"], diseases)
        self.assertTrue(context["has_diseases"])

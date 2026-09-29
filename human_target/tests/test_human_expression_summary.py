from django.test import SimpleTestCase

from human_target.services.human_expression_summary import build_human_expression_context


class _FakeHumanProtein:
    def __init__(self, expression_json):
        self.expression_json = expression_json


class BuildHumanExpressionContextTests(SimpleTestCase):
    def test_reports_no_expression_for_empty_list(self):
        context = build_human_expression_context(_FakeHumanProtein([]))
        self.assertFalse(context["has_expression"])
        self.assertEqual(context["total_count"], 0)
        self.assertIsNone(context["peak"])
        self.assertEqual(context["system_groups"], [])

    def test_ranks_by_score_descending_and_finds_peak(self):
        rows = [
            {"tissue": "kidney", "score": 40.0, "quality": "silver"},
            {"tissue": "heart", "score": 90.0, "quality": "gold"},
            {"tissue": "liver", "score": 60.0, "quality": "gold"},
        ]
        context = build_human_expression_context(_FakeHumanProtein(rows))
        self.assertTrue(context["has_expression"])
        self.assertEqual(context["total_count"], 3)
        self.assertEqual(context["peak"]["tissue"], "heart")
        self.assertEqual([r["tissue"] for r in context["ranked"]], ["heart", "liver", "kidney"])
        self.assertEqual(context["gold_count"], 2)

    def test_buckets_tissues_into_anatomical_systems(self):
        rows = [
            {"tissue": "heart muscle", "score": 80.0, "quality": "gold"},
            {"tissue": "kidney cortex", "score": 50.0, "quality": "silver"},
            {"tissue": "some obscure structure", "score": 10.0, "quality": "bronze"},
        ]
        context = build_human_expression_context(_FakeHumanProtein(rows))
        systems = {group["system"] for group in context["system_groups"]}
        self.assertIn("Cardiovascular", systems)
        self.assertIn("Urinary", systems)
        self.assertIn("Other", systems)

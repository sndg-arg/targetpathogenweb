import gzip
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from tpweb.models.LigandRoutePlan import LigandRoutePlan
from tpweb.services.ligand_routes import plan_summaries, plans_loaded, route_plan

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
# Aspirin from salicylic acid, whose ring half is itself made in a first step.
PLAN = {
    "ligand_smiles": ASPIRIN,
    "solved": False,
    "depth": 2,
    "steps": 2,
    "leaves": 3,
    "available_leaves": 2,
    "tree": {
        "smiles": ASPIRIN,
        "available": False,
        "reaction": {
            "id": "US04927956",
            "class": 2,
            "name": "Acylation",
            "reagents": "",
            "reactants": "CC(=O)Cl.O=C(O)c1ccccc1O",
        },
        "precursors": [
            {"smiles": "CC(=O)Cl", "available": True, "reaction": None, "precursors": []},
            {
                "smiles": "O=C(O)c1ccccc1O",
                "available": False,
                "reaction": {
                    "id": "US20020142971A1;0090;39985",
                    "class": None,
                    "name": "",
                    "reagents": "O=S(=O)(O)O",
                    "reactants": "Oc1ccccc1.O=C=O",
                },
                "precursors": [
                    {"smiles": "Oc1ccccc1", "available": True, "reaction": None, "precursors": []},
                    {"smiles": "O=C=O", "available": False, "reaction": None, "precursors": []},
                ],
            },
        ],
    },
}


@override_settings(CACHES=LOCMEM)
class LigandRoutePlanTests(TestCase):
    def _load(self, records=(PLAN,)):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plans.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record) + "\n")
            call_command("load_ligand_routes", str(path))

    def test_loads_replaces_and_skips_repeated_ligands(self):
        self.assertFalse(plans_loaded())
        self._load(records=(PLAN, PLAN))
        self.assertEqual(LigandRoutePlan.objects.count(), 1)
        self._load()
        self.assertEqual(LigandRoutePlan.objects.count(), 1)
        self.assertTrue(plans_loaded())
        plan = LigandRoutePlan.objects.get()
        self.assertEqual((plan.steps, plan.depth, plan.leaves), (2, 2, 3))
        self.assertFalse(plan.solved)

    def test_numbers_the_steps_in_the_order_they_are_carried_out(self):
        self._load()
        rendered = route_plan(ASPIRIN)
        # The deepest reaction runs first, so the last step makes the ligand.
        self.assertEqual(rendered["tree"]["step"], 2)
        salicylic = rendered["tree"]["precursors"][1]
        self.assertEqual(salicylic["step"], 1)
        self.assertEqual(salicylic["reagents"], "O=S(=O)(O)O")
        self.assertEqual(rendered["tree"]["class_label"], "Acylation")
        # The name repeats the class label, so it is not shown twice.
        self.assertEqual(rendered["tree"]["name"], "")
        self.assertEqual(
            rendered["tree"]["patent"],
            {"number": "US4927956", "url": "https://patents.google.com/patent/US4927956"},
        )

    def test_reports_the_branches_that_stay_open(self):
        self._load()
        rendered = route_plan(ASPIRIN)
        self.assertFalse(rendered["solved"])
        self.assertEqual(rendered["open_leaves"], 1)
        leaves = rendered["tree"]["precursors"][1]["precursors"]
        self.assertEqual([leaf["available"] for leaf in leaves], [True, False])
        self.assertEqual([leaf["step"] for leaf in leaves], [None, None])

    def test_a_ligand_without_a_plan_has_none(self):
        self._load()
        self.assertIsNone(route_plan("CCO"))
        self.assertIsNone(route_plan(""))

    def test_plan_summaries_only_answers_for_known_keys(self):
        self._load()
        key = LigandRoutePlan.objects.get().smiles_key
        self.assertEqual(plan_summaries([key]), {key: {"steps": 2, "solved": False}})
        self.assertEqual(plan_summaries([]), {})
        self.assertEqual(plan_summaries(["missing"]), {})

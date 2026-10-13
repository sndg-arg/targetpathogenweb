from types import SimpleNamespace

from django.test import SimpleTestCase

from tpweb.services.protein_formula import structure_dependent_columns
from tpweb.services.protein_summary import build_target_executive_summary


def _summary(raw_scores, metabolic_context=None, microbiome_context=None, binders=None):
    return build_target_executive_summary(
        raw_scores,
        structure_summary={"has_structure": True, "source": "alphafold", "label": "AlphaFold"},
        selected_pocket_evidence=None,
        conservation_profile=None,
        microbiome_context=microbiome_context,
        metabolic_context=metabolic_context,
        binders=binders,
    )


class TargetSummaryVerdictTests(SimpleTestCase):
    def test_verdict_does_not_claim_metabolic_evidence_without_metabolic_context(self):
        result = _summary(
            {"human_offtarget": "no_hit", "Druggability": "0.9", "p2rank_probability": "0.8"},
            binders={"summary": {"direct_count": 5}},
        )
        self.assertNotIn("metabolic", result["verdict"])
        self.assertIn("structural", result["verdict"])
        self.assertIn("chemical", result["verdict"])

    def test_gut_microbiome_hit_is_a_risk_even_without_curated_microbiome_context(self):
        result = _summary({"gut_microbiome_offtarget": "hit"}, microbiome_context=None)
        self.assertIn("Microbiome similarity", [item["label"] for item in result["risks"]])

    def test_verdict_points_to_flagged_risks(self):
        result = _summary({"gut_microbiome_offtarget": "hit", "Druggability": "0.9"})
        self.assertIn("flagged risk", result["verdict"])


class StructureDependentColumnsTests(SimpleTestCase):
    def test_only_pocket_and_structure_columns_are_structure_dependent(self):
        score_dict = {
            "Druggability": SimpleNamespace(category="Pocket"),
            "p2rank_probability": SimpleNamespace(category="Pocket"),
            "colabfold_plddt": SimpleNamespace(category="Pocket"),
            "human_offtarget": SimpleNamespace(category="Off-target"),
            "hit_in_deg": SimpleNamespace(category="Essentiality"),
            "Localization": SimpleNamespace(category="Localization"),
        }
        self.assertEqual(
            structure_dependent_columns(score_dict),
            {"Druggability", "p2rank_probability", "colabfold_plddt"},
        )

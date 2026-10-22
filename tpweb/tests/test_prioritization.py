from django.test import SimpleTestCase

from tpweb.services.protein_summary import (
    build_conservation_profile,
    build_microbiome_context,
    build_prioritization,
    build_selected_pocket_evidence,
    build_target_profile,
)


class PrioritizationTests(SimpleTestCase):
    def build(self, raw):
        microbiome = build_microbiome_context(raw)
        return build_prioritization(
            raw,
            build_target_profile(raw, microbiome_context=microbiome),
            build_selected_pocket_evidence(raw),
            build_conservation_profile(raw),
            microbiome,
            None,
        )

    def test_one_block_per_question_with_structure_kept_apart(self):
        result = self.build(
            {
                "hit_in_deg": "N",
                "core_roary": "True",
                "core_corecruncher": "True",
                "human_offtarget": "no_hit",
                "gut_microbiome_offtarget": "hit",
                "gut_microbiome_offtarget_counts": "85",
                "gut_microbiome_genomes_analyzed": "4744",
                "p2rank_probability": "0.998",
                "best_p2rank_structure": "A0A0H3GUK9",
                "Druggability": "0.958",
                "colabfold_plddt": "96.24",
                "pocket_size_outlier": "Y",
            }
        )
        self.assertEqual(
            [(g["key"], g["verdict"]) for g in result["groups"]],
            [
                ("essentiality", "Not essential"),
                ("conservation", "Core gene"),
                ("off_target", "Low risk"),
            ],
        )
        structure = result["structure"]
        self.assertEqual(structure["verdict"], "Druggable pocket")
        self.assertTrue(structure["rows"][0]["outlier"])
        self.assertEqual(structure["rows"][-1]["plddt"], "96.24")
        self.assertEqual(
            [(v["label"], v["value"]) for v in result["summary"]][-1], ("Druggable", "Yes")
        )

    def test_nothing_to_show_returns_none(self):
        self.assertIsNone(self.build({}))

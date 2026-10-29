from django.test import SimpleTestCase

from tpweb.services.protein_summary import (
    build_conservation_profile,
    build_gates_regulatory,
    build_localization,
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
        # Each verdict links to its row; each row carries a one-line finding.
        self.assertEqual(result["summary"][-1]["href"], "#binding-site-evidence")
        self.assertTrue(all(group["finding"] for group in result["groups"]))
        self.assertIn("P2Rank", structure["finding"])

    def test_nothing_to_show_returns_none(self):
        self.assertIsNone(self.build({}))

    def test_curated_regulatory_group(self):
        raw = {
            "grn_role": "Master regulator",
            "grn_knockout_score": "0.0003059",
            "grn_transcription_factor": "Y",
            "grn_regulated": "N",
        }
        result = build_prioritization(raw, [], None, None, None, None, build_gates_regulatory(raw))
        (group,) = result["groups"]
        self.assertEqual(
            (group["key"], group["verdict"], group["tone"], group["badge"]),
            ("regulatory", "Master regulator", "success", "Curated"),
        )
        self.assertEqual(
            [(item["label"], item["value"]) for item in group["items"]],
            [
                ("Network role", "Master regulator"),
                ("Knockout impact", "3.06e-04"),
                ("Transcription factor", "Yes"),
                ("Regulated by a transcription factor", "No"),
            ],
        )
        self.assertEqual(result["summary"][0]["value"], "Master regulator")

    def test_peripheral_role_is_neutral_and_genes_outside_the_grn_get_nothing(self):
        peripheral = build_gates_regulatory({"grn_role": "Peripheral"})
        self.assertFalse(peripheral["is_central"])
        self.assertIsNone(build_gates_regulatory({"grn_transcription_factor": "N"}))


class RegulatoryImportTests(SimpleTestCase):
    def test_uploaded_values_map_to_curated_ones(self):
        from tpweb.management.commands.load_gates_regulatory_score import curated_value

        self.assertEqual(curated_value("grn_role", "master_regulator"), "Master regulator")
        self.assertEqual(curated_value("grn_role", "."), "")
        self.assertEqual(curated_value("grn_transcription_factor", "TF"), "Y")
        self.assertEqual(curated_value("grn_regulated", ""), "N")
        self.assertEqual(curated_value("grn_knockout_score", "0.0002046"), "0.0002046")


class LocalizationTests(SimpleTestCase):
    def test_psortb_value_lights_its_envelope_part(self):
        profile = [{"key": "Localization", "value": "Periplasmic", "tooltip": "t"}]
        self.assertEqual(build_localization(profile)["parts"], ["periplasm"])
        unknown = [{"key": "Localization", "value": "Unknown"}]
        self.assertEqual(build_localization(unknown)["parts"], [])
        self.assertIsNone(build_localization([]))


class RegulatoryIsStrainLocalTests(SimpleTestCase):
    def test_grn_scores_are_not_shared_across_identical_proteins(self):
        from types import SimpleNamespace

        from tpweb.services.shared_sequence_evidence import sequence_specific_score

        for name in ("grn_regulated", "GRN_knockout_score"):
            param = SimpleNamespace(name=name, category="Regulatory (curated)")
            self.assertFalse(sequence_specific_score(param))


class SmallScoreDisplayTests(SimpleTestCase):
    def test_tiny_scores_switch_to_scientific_notation(self):
        from tpweb.templatetags.custom_tags import score_metric_display

        self.assertEqual(score_metric_display("0.0003059", "grn_knockout_score"), "3.06e-04")
        self.assertEqual(score_metric_display("0.196", "grn_knockout_score"), "0.196")
        self.assertEqual(score_metric_display("0", "grn_knockout_score"), "0.000")

    def test_uploaded_grn_columns_get_the_shared_help(self):
        from types import SimpleNamespace

        from tpweb.services.score_params import GATES_REGULATORY_HELP, column_help

        blank = SimpleNamespace(name="GRN_category", description="")
        self.assertEqual(column_help(blank), GATES_REGULATORY_HELP["grn_role"])
        own = SimpleNamespace(name="GRN_category", description="Her text")
        self.assertEqual(column_help(own), "Her text")

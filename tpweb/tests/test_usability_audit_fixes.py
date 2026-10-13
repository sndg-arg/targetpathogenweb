from types import SimpleNamespace

from django.test import SimpleTestCase

from tpweb.services.protein_annotations import _dbxref_label
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


def _dbxref(accession, dbname, name="", definition="", identifier=""):
    term = SimpleNamespace(name=name, definition=definition, identifier=identifier or accession)
    terms = SimpleNamespace(all=lambda: [SimpleNamespace(term=term)])
    return SimpleNamespace(accession=accession, dbname=dbname, terms=terms)


class AnnotationLabelTests(SimpleTestCase):
    def test_go_label_is_the_term_name_not_the_long_definition(self):
        dbxref = _dbxref(
            "GO:0005829",
            "GO",
            name="cytosol",
            definition="The part of the cytoplasm that does not contain organelles...",
        )
        self.assertEqual(_dbxref_label(dbxref), "cytosol")

    def test_falls_back_to_definition_when_name_just_repeats_the_identifier(self):
        dbxref = _dbxref("GO:0000001", "GO", name="GO:0000001", definition="Some definition.")
        self.assertEqual(_dbxref_label(dbxref), "Some definition.")


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

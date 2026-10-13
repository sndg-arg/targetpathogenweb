from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from tpweb.models.PipelineRun import PipelineRun
from tpweb.services.formula_evaluator import formula_uses_missing_params
from tpweb.services.genome_upload_status import reconcile_genome_uploads

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


class StaleUnlinkedPipelineRunTests(TestCase):
    def _run(self, accession, age_hours):
        run = PipelineRun.objects.create(
            genome_upload=None,
            internal_accession=accession,
            source_accession=accession,
            gram="n",
            status=PipelineRun.STATUS_RUNNING,
        )
        # auto_now would overwrite updated_at on save(); set it directly.
        PipelineRun.objects.filter(pk=run.pk).update(
            updated_at=django_timezone.now() - timedelta(hours=age_hours)
        )
        return run

    def test_stale_run_without_upload_is_failed_and_fresh_one_is_kept(self):
        stale = self._run("public__STALE", age_hours=30)
        fresh = self._run("public__FRESH", age_hours=2)

        reconcile_genome_uploads()

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, PipelineRun.STATUS_FAILED)
        self.assertIsNone(stale.launch_pid)
        self.assertEqual(fresh.status, PipelineRun.STATUS_RUNNING)


class FormulaMissingParamsTests(SimpleTestCase):
    var_to_param = {
        "colabfold_druggability_score": "colabfold_druggability_score",
        "druggability": "Druggability",
        "hit_in_deg_y": "hit_in_deg",
    }

    def _formula(self, expression="", term_params=()):
        terms = [SimpleNamespace(score_param=SimpleNamespace(name=name)) for name in term_params]
        return SimpleNamespace(expression=expression, terms=SimpleNamespace(all=lambda: terms))

    def test_expression_using_a_param_the_genome_lacks_is_flagged(self):
        formula = self._formula("0.5 * colabfold_druggability_score + druggability")
        self.assertTrue(formula_uses_missing_params(formula, {"Druggability"}, self.var_to_param))

    def test_expression_fully_covered_by_the_genome_is_kept(self):
        formula = self._formula("druggability + 2 * hit_in_deg_y")
        self.assertFalse(
            formula_uses_missing_params(formula, {"Druggability", "hit_in_deg"}, self.var_to_param)
        )

    def test_term_based_formula_checks_its_terms(self):
        formula = self._formula(term_params=("Localization",))
        self.assertTrue(formula_uses_missing_params(formula, {"Druggability"}, self.var_to_param))

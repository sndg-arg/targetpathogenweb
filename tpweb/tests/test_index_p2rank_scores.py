from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB, PDBResidueSet, ResidueSet, ResidueSetProperty, Property
from tpweb.management.commands.index_p2rank_scores import BUNDLE, Command, candidate_key


class IndexP2RankScoresTests(TestCase):
    def setUp(self):
        self.genome = "public__p2rank_index_test"
        database = Biodatabase.objects.create(name=self.genome + Biodatabase.PROT_POSTFIX)
        self.protein = Bioentry.objects.create(
            biodatabase=database, accession="P2TEST_1", name="P2TEST_1", identifier="P2TEST_1"
        )
        self.kind = ResidueSet.objects.create(name="P2RankPocket")
        self.property = Property.objects.create(name="probability")

    def candidate(self, code, probability, experiment="CF", name="1", chain=""):
        pdb = PDB.objects.create(code=code, experiment=experiment)
        link = BioentryStructure.objects.create(bioentry=self.protein, pdb=pdb, chain=chain)
        pocket = PDBResidueSet.objects.create(pdb=pdb, residue_set=self.kind, name=name)
        ResidueSetProperty.objects.create(
            pdbresidue_set=pocket, property=self.property, value=probability
        )
        return link, pocket

    def run_index(self, apply=True):
        output = StringIO()

        # Test the real indexing queries/writes; metadata initialization has
        # separate tests and is independent of pocket selection.
        def ensure(name):
            return ScoreParam.objects.get_or_create(
                name=name,
                category="Pocket",
                user=None,
                defaults={"type": "N", "default_operation": ">=", "default_value": "0"},
            )[0]

        with patch(
            "tpweb.services.score_params.ensure_system_score_param", side_effect=ensure, create=True
        ):
            Command(stdout=output).handle(genome_name=self.genome, apply=apply)
        return output.getvalue()

    def values(self):
        return {
            row.score_param.name: row
            for row in ScoreParamValue.objects.filter(bioentry=self.protein).select_related(
                "score_param"
            )
        }

    def test_preview_does_not_create_parameters_or_values(self):
        self.candidate("CF_TEST", 0.8)
        self.assertIn("Would index: 1", self.run_index(apply=False))
        self.assertEqual(ScoreParam.objects.count(), 0)
        self.assertEqual(ScoreParamValue.objects.count(), 0)

    def test_probability_and_references_describe_the_same_best_pocket(self):
        self.candidate("CF_LOW", 0.2)
        self.candidate("CF_HIGH", 0.8, name="7")
        self.run_index()
        values = self.values()
        self.assertEqual(values[BUNDLE[0]].numeric_value, 0.8)
        self.assertEqual(values[BUNDLE[1]].value, "CF_HIGH")
        self.assertEqual(values[BUNDLE[2]].value, "7")
        self.assertIn("Indexed: 0", self.run_index())
        self.assertEqual(ScoreParamValue.objects.count(), 3)

    def test_experimental_pocket_has_precedence_over_model(self):
        self.candidate("CF_HIGH", 0.9)
        self.candidate("EX_TEST", 0.5, experiment="EX")
        self.run_index()
        self.assertEqual(self.values()[BUNDLE[1]].value, "EX_TEST")

    def test_zero_is_preserved_and_no_pockets_do_not_create_false_zero_scores(self):
        self.assertIn("Indexed: 0", self.run_index())
        self.assertEqual(ScoreParam.objects.count(), 0)
        self.candidate("CF_ZERO", 0.0)
        self.run_index()
        self.assertEqual(self.values()[BUNDLE[0]].numeric_value, 0)

    def test_partial_curated_selection_is_not_overwritten(self):
        self.candidate("CF_TEST", 0.8)
        param = ScoreParam.objects.create(
            name=BUNDLE[1],
            category="Pocket",
            user=None,
            type="C",
            default_operation="=",
            default_value="",
        )
        ScoreParamValue.objects.create(bioentry=self.protein, score_param=param, value="CURATED")
        self.assertIn("preserved existing selections: 1", self.run_index())
        self.assertEqual(ScoreParamValue.objects.count(), 1)
        self.assertEqual(self.values()[BUNDLE[1]].value, "CURATED")

    def test_invalid_probabilities_are_rejected(self):
        link, pocket = self.candidate("CF_TEST", 0.8)
        for value in [None, -0.1, 1.1, float("inf"), float("nan")]:
            self.assertIsNone(candidate_key(link, pocket.pk, value))

    def test_legacy_property_and_blank_existing_score_can_be_recovered(self):
        self.property.name = "P2Rrank probability"
        self.property.save()
        self.candidate("CF_LEGACY", 0.55)
        param = ScoreParam.objects.create(
            name=BUNDLE[0],
            category="Pocket",
            user=None,
            type="N",
            default_operation=">=",
            default_value="0",
        )
        blank = ScoreParamValue.objects.create(bioentry=self.protein, score_param=param, value="")
        self.run_index()
        blank.refresh_from_db()
        self.assertEqual(blank.numeric_value, 0.55)
        self.assertEqual(ScoreParamValue.objects.count(), 3)

    def test_chain_scope_is_applied_before_choosing_pocket(self):
        self.candidate("CF_WRONG_CHAIN", 0.99, chain="B")
        self.candidate("CF_UNRESTRICTED", 0.5)
        # A linked B chain without B pocket residues must not win.
        self.run_index()
        self.assertEqual(self.values()[BUNDLE[1]].value, "CF_UNRESTRICTED")

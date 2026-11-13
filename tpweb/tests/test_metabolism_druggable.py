from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.services.metabolism_summary import druggable_protein_ids


class DruggableProteinIdsTests(TestCase):
    def test_fpocket_or_p2rank_over_the_protein_page_bar(self):
        proteome = Biodatabase.objects.create(name="DRUG_protein")
        fpocket, _ = ScoreParam.objects.get_or_create(
            category="Pocket", name="Druggability", user=None
        )
        p2rank, _ = ScoreParam.objects.get_or_create(
            category="Pocket", name="p2rank_probability", user=None
        )
        proteins = {}
        for accession, param, score in (
            ("FPOCKET_HIGH", fpocket, 0.82),
            ("FPOCKET_LOW", fpocket, 0.55),
            ("P2RANK_HIGH", p2rank, 0.61),
            ("P2RANK_LOW", p2rank, 0.2),
        ):
            protein = Bioentry.objects.create(
                biodatabase=proteome, name=accession, accession=accession, identifier=accession
            )
            ScoreParamValue.objects.create(
                bioentry=protein, score_param=param, value=str(score), numeric_value=score
            )
            proteins[accession] = protein.pk

        self.assertEqual(
            druggable_protein_ids(proteins.values()),
            {proteins["FPOCKET_HIGH"], proteins["P2RANK_HIGH"]},
        )

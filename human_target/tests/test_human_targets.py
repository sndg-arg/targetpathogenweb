from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_targets import (
    HUMAN_BIODATABASE_NAME,
    human_proteins_queryset,
)


class HumanProteinsQuerysetTests(TestCase):
    """DB-side search replacement for the old Python-side substring filter --
    needs to scale to the full proteome, not just the 10-protein pilot."""

    def _make_human_protein(self, accession, gene_symbol, protein_name):
        biodatabase, _ = Biodatabase.objects.get_or_create(name=HUMAN_BIODATABASE_NAME)
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        return HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession=accession,
            gene_symbol=gene_symbol,
            protein_name=protein_name,
        )

    def test_no_query_returns_everything(self):
        self._make_human_protein("P10721", "KIT", "Mast/stem cell growth factor receptor Kit")
        self._make_human_protein("O00116", "AGPS", "Alkyldihydroxyacetonephosphate synthase")

        self.assertEqual(human_proteins_queryset().count(), 2)

    def test_query_matches_accession_case_insensitively(self):
        self._make_human_protein("P10721", "KIT", "Mast/stem cell growth factor receptor Kit")
        self._make_human_protein("O00116", "AGPS", "Alkyldihydroxyacetonephosphate synthase")

        result = human_proteins_queryset("p107")
        self.assertEqual([hp.uniprot_accession for hp in result], ["P10721"])

    def test_query_matches_gene_symbol(self):
        self._make_human_protein("P10721", "KIT", "Mast/stem cell growth factor receptor Kit")
        self._make_human_protein("O00116", "AGPS", "Alkyldihydroxyacetonephosphate synthase")

        result = human_proteins_queryset("kit")
        self.assertEqual([hp.uniprot_accession for hp in result], ["P10721"])

    def test_query_matches_protein_name_substring(self):
        self._make_human_protein("P10721", "KIT", "Mast/stem cell growth factor receptor Kit")
        self._make_human_protein("O00116", "AGPS", "Alkyldihydroxyacetonephosphate synthase")

        result = human_proteins_queryset("growth factor")
        self.assertEqual([hp.uniprot_accession for hp in result], ["P10721"])

    def test_query_with_no_matches_returns_empty(self):
        self._make_human_protein("P10721", "KIT", "Mast/stem cell growth factor receptor Kit")

        self.assertEqual(human_proteins_queryset("doesnotexist").count(), 0)

    def test_excludes_proteins_outside_the_human_biodatabase(self):
        other_db = Biodatabase.objects.create(name="public__SOMEGENOME_prots")
        other_bioentry = Bioentry.objects.create(
            biodatabase=other_db, name="LOCUS1", accession="LOCUS1", identifier="LOCUS1"
        )
        HumanProtein.objects.create(bioentry=other_bioentry, uniprot_accession="LOCUS1")

        self.assertEqual(human_proteins_queryset().count(), 0)

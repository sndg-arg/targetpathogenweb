from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry

from human_target.models.HumanPathway import HumanPathway
from human_target.models.HumanProtein import HumanProtein
from human_target.models.HumanProteinPathway import HumanProteinPathway
from human_target.services.human_pathway_summary import build_human_pathway_context


class BuildHumanPathwayContextTests(TestCase):
    def _make_human_protein(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        return HumanProtein.objects.create(bioentry=bioentry, uniprot_accession=accession)

    def test_reports_no_pathways_when_unlinked(self):
        human_protein = self._make_human_protein("P10721")
        context = build_human_pathway_context(human_protein)
        self.assertFalse(context["has_pathways"])
        self.assertEqual(context["pathways"], [])
        self.assertEqual(context["default_kegg_id"], "")

    def test_shapes_linked_pathways_and_picks_first_as_default(self):
        human_protein = self._make_human_protein("P10721")
        pathway = HumanPathway.objects.create(
            kegg_id="hsa04010",
            title="MAPK signaling pathway",
            entry_count=2,
            relation_count=1,
            graph_json={"nodes": [], "edges": []},
        )
        HumanProteinPathway.objects.create(
            human_protein=human_protein, pathway=pathway, highlighted_node_id="1"
        )

        context = build_human_pathway_context(human_protein)

        self.assertTrue(context["has_pathways"])
        self.assertEqual(context["default_kegg_id"], "hsa04010")
        self.assertEqual(context["pathways"][0]["highlighted_node_id"], "1")

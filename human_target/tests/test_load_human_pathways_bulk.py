import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_pathways_bulk import (
    _gene_ids_from_cross_references,
    _parse_link_table,
)
from human_target.models.HumanPathway import HumanPathway
from human_target.models.HumanProtein import HumanProtein
from human_target.models.HumanProteinPathway import HumanProteinPathway

_LINK_TABLE_TEXT = "hsa:5594\tpath:hsa04010\nhsa:5594\tpath:hsa05200\nhsa:5595\tpath:hsa04010\n"

_SAMPLE_KGML = """<?xml version="1.0"?>
<pathway name="path:hsa04010" org="hsa" number="04010" title="MAPK signaling pathway">
  <entry id="1" name="hsa:5594" type="gene">
    <graphics name="MAPK1, ERK2" type="rectangle"/>
  </entry>
  <entry id="2" name="hsa:5595" type="gene">
    <graphics name="MAPK3, ERK1" type="rectangle"/>
  </entry>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation"/>
  </relation>
</pathway>
"""


class ParseLinkTableTests(SimpleTestCase):
    def test_parses_tab_separated_gene_to_pathway_links(self):
        mapping = _parse_link_table(_LINK_TABLE_TEXT)
        self.assertEqual(mapping["5594"], {"hsa04010", "hsa05200"})
        self.assertEqual(mapping["5595"], {"hsa04010"})

    def test_blank_lines_are_ignored(self):
        mapping = _parse_link_table("\n" + _LINK_TABLE_TEXT + "\n\n")
        self.assertEqual(set(mapping), {"5594", "5595"})


class GeneIdsFromCrossReferencesTests(SimpleTestCase):
    def test_extracts_geneid_xrefs_only(self):
        xrefs = [
            {"database": "RefSeq", "id": "NP_000001"},
            {"database": "GeneID", "id": "5594"},
        ]
        self.assertEqual(_gene_ids_from_cross_references(xrefs), ["5594"])

    def test_no_geneid_returns_empty_list(self):
        self.assertEqual(_gene_ids_from_cross_references([{"database": "RefSeq", "id": "x"}]), [])
        self.assertEqual(_gene_ids_from_cross_references([]), [])
        self.assertEqual(_gene_ids_from_cross_references(None), [])


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _fake_get(url, timeout=None):
    if url.endswith("/link/pathway/hsa"):
        return _FakeResponse(_LINK_TABLE_TEXT)
    return _FakeResponse(_SAMPLE_KGML)


class LoadHumanPathwaysBulkTests(TestCase):
    def _make_human_protein(self, accession, gene_id=""):
        biodatabase, _ = Biodatabase.objects.get_or_create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        cross_refs = [{"database": "GeneID", "id": gene_id}] if gene_id else []
        return HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession=accession,
            cross_references_raw=cross_refs,
        )

    @patch(
        "human_target.management.commands.load_human_pathways_bulk.requests.get",
        side_effect=_fake_get,
    )
    def test_creates_pathway_and_link_with_highlighted_node(self, mock_get):
        self._make_human_protein("P10721", gene_id="5594")

        call_command("load_human_pathways_bulk", accession=["P10721"])

        pathway = HumanPathway.objects.get(kegg_id="hsa04010")
        self.assertEqual(pathway.title, "MAPK signaling pathway")
        self.assertEqual(pathway.entry_count, 2)
        self.assertEqual(pathway.relation_count, 1)
        link = HumanProteinPathway.objects.get(pathway=pathway)
        self.assertEqual(link.highlighted_node_id, "1")

    @patch(
        "human_target.management.commands.load_human_pathways_bulk.requests.get",
        side_effect=_fake_get,
    )
    def test_sharing_a_pathway_reuses_the_same_pathway_row(self, mock_get):
        self._make_human_protein("P10721", gene_id="5594")
        self._make_human_protein("P10722", gene_id="5595")

        call_command("load_human_pathways_bulk", accession=["P10721", "P10722"])

        self.assertEqual(HumanPathway.objects.filter(kegg_id="hsa04010").count(), 1)
        second_link = HumanProteinPathway.objects.get(
            human_protein__uniprot_accession="P10722", pathway__kegg_id="hsa04010"
        )
        self.assertEqual(second_link.highlighted_node_id, "2")
        # P10721's gene (5594) is also in hsa05200, which only it belongs to.
        self.assertTrue(
            HumanProteinPathway.objects.filter(
                human_protein__uniprot_accession="P10721", pathway__kegg_id="hsa05200"
            ).exists()
        )

    @patch(
        "human_target.management.commands.load_human_pathways_bulk.requests.get",
        side_effect=_fake_get,
    )
    def test_protein_without_geneid_is_skipped_without_error(self, mock_get):
        self._make_human_protein("P10721")

        call_command("load_human_pathways_bulk", accession=["P10721"])

        self.assertEqual(HumanProteinPathway.objects.count(), 0)
        mock_get.assert_not_called()

    @patch(
        "human_target.management.commands.load_human_pathways_bulk.requests.get",
        side_effect=_fake_get,
    )
    def test_dry_run_writes_nothing(self, mock_get):
        self._make_human_protein("P10721", gene_id="5594")

        call_command("load_human_pathways_bulk", accession=["P10721"], dry_run=True)

        self.assertEqual(HumanPathway.objects.count(), 0)
        self.assertEqual(HumanProteinPathway.objects.count(), 0)

    @patch(
        "human_target.management.commands.load_human_pathways_bulk.requests.get",
        side_effect=_fake_get,
    )
    def test_accession_file_is_added_to_the_restriction(self, mock_get):
        self._make_human_protein("P10721", gene_id="5594")
        self._make_human_protein("P10722", gene_id="5595")

        with tempfile.TemporaryDirectory() as tmp:
            accession_file = Path(tmp) / "accessions.txt"
            accession_file.write_text("P10722\n", encoding="utf-8")
            call_command("load_human_pathways_bulk", accession_file=str(accession_file))

        self.assertFalse(
            HumanProteinPathway.objects.filter(human_protein__uniprot_accession="P10721").exists()
        )
        self.assertTrue(
            HumanProteinPathway.objects.filter(human_protein__uniprot_accession="P10722").exists()
        )

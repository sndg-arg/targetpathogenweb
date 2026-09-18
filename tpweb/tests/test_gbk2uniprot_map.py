"""Tests for gbk2uniprot_map.py's RefSeq-xref fallback search -- the parser
that turns a UniProtKB TSV search response into per-RefSeq-id mapping rows
when the async idmapping API fails (see CLAUDE.md's "UniProt prerequisite"
note on binders). Uses a mocked requests.Session so no network call happens.
"""

from unittest.mock import Mock

from django.test import SimpleTestCase

from tpweb.management.commands.gbk2uniprot_map import Command


class SearchRefseqBatchTests(SimpleTestCase):
    def test_empty_ids_returns_empty_dataframe_without_a_request(self):
        command = Command()
        session = Mock()

        result = command._search_refseq_batch(session, [])

        self.assertTrue(result.empty)
        session.get.assert_not_called()

    def test_parses_matching_rows_from_tsv_response(self):
        command = Command()
        response = Mock()
        response.text = (
            "Entry\tEntry Name\tReviewed\tProtein names\tGene Names\tOrganism\tLength\tRefSeq\n"
            "P12345\tGENE_HUMAN\treviewed\tTest protein\tGENE\tHomo sapiens\t100\tNP_000001;NP_000002\n"
        )
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response

        result = command._search_refseq_batch(session, ["NP_000001"])

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["From"], "NP_000001")
        self.assertEqual(row["Entry"], "P12345")
        self.assertEqual(row["Reviewed"], "reviewed")

    def test_ids_not_present_in_response_are_dropped(self):
        command = Command()
        response = Mock()
        response.text = (
            "Entry\tEntry Name\tReviewed\tProtein names\tGene Names\tOrganism\tLength\tRefSeq\n"
            "P12345\tGENE_HUMAN\treviewed\tTest protein\tGENE\tHomo sapiens\t100\tNP_999999\n"
        )
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response

        result = command._search_refseq_batch(session, ["NP_000001"])

        self.assertTrue(result.empty)

    def test_missing_expected_columns_returns_empty_dataframe(self):
        command = Command()
        response = Mock()
        response.text = "SomeColumn\nvalue\n"
        response.raise_for_status = Mock()
        session = Mock()
        session.get.return_value = response

        result = command._search_refseq_batch(session, ["NP_000001"])

        self.assertTrue(result.empty)

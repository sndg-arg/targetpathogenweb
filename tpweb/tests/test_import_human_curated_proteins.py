"""Tests for import_human_curated_proteins.py's UniProt JSON extraction
helpers. These are plain-dict-in/dict-out functions (no DB, no bioseq
dependency) that parse the UniProtKB REST response shape -- per the
command's own module docstring, that shape was never validated against a
real downloaded file in this environment, so these fixtures are built
directly from the field paths the code reads, not from a live sample.
"""

import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from tpweb.management.commands.import_human_curated_proteins import (
    _build_human_protein_fields,
    _extract_comments,
    _extract_catalytic_activity,
    _extract_cross_references,
    _extract_ec_numbers,
    _extract_features,
    _extract_go_terms,
    _extract_keywords,
    _extract_publications,
    _extract_subcellular_locations,
    _load_json,
    _texts_for_comment,
)


class LoadJsonTests(SimpleTestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(_load_json(Path("/does/not/exist.json")))

    def test_reads_and_parses_json_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"primaryAccession": "P12345"}, f)
            path = Path(f.name)
        try:
            self.assertEqual(_load_json(path), {"primaryAccession": "P12345"})
        finally:
            path.unlink()


class TextsForCommentTests(SimpleTestCase):
    def test_strips_and_drops_empty_values(self):
        comment = {"texts": [{"value": "  Some function text.  "}, {"value": ""}]}
        self.assertEqual(_texts_for_comment(comment), ["Some function text."])


class ExtractCommentsTests(SimpleTestCase):
    def test_maps_known_comment_types_and_collects_diseases(self):
        entry = {
            "comments": [
                {"commentType": "FUNCTION", "texts": [{"value": "Catalyzes X."}]},
                {
                    "commentType": "DISEASE",
                    "disease": {
                        "diseaseId": "Disease A",
                        "acronym": "DA",
                        "description": "desc",
                        "diseaseCrossReference": {"id": "MIM:12345"},
                    },
                },
            ]
        }

        out, diseases = _extract_comments(entry)

        self.assertEqual(
            out,
            {
                "function_text": "Catalyzes X.",
                "caution_text": "",
                "subunit_text": "",
                "polymorphism_text": "",
            },
        )
        self.assertEqual(
            diseases,
            [{"name": "Disease A", "acronym": "DA", "description": "desc", "mim": "MIM:12345"}],
        )

    def test_empty_comments_list_returns_blank_fields(self):
        out, diseases = _extract_comments({})
        self.assertEqual(
            out,
            {
                "function_text": "",
                "caution_text": "",
                "subunit_text": "",
                "polymorphism_text": "",
            },
        )
        self.assertEqual(diseases, [])


class ExtractCatalyticActivityTests(SimpleTestCase):
    def test_reads_ec_rhea_and_reaction_name(self):
        entry = {
            "comments": [
                {
                    "commentType": "CATALYTIC ACTIVITY",
                    "reaction": {
                        "ecNumber": "1.1.1.1",
                        "name": "A + B = C",
                        "reactionCrossReferences": [
                            {"database": "ChEBI", "id": "CHEBI:1"},
                            {"database": "Rhea", "id": "RHEA:12345"},
                        ],
                    },
                }
            ]
        }

        self.assertEqual(
            _extract_catalytic_activity(entry),
            [{"ec": "1.1.1.1", "rhea": "RHEA:12345", "reaction": "A + B = C"}],
        )

    def test_ignores_non_catalytic_activity_comments(self):
        entry = {"comments": [{"commentType": "FUNCTION", "texts": []}]}
        self.assertEqual(_extract_catalytic_activity(entry), [])


class ExtractEcNumbersTests(SimpleTestCase):
    def test_collects_ec_numbers_from_recommended_and_alternative_names(self):
        entry = {
            "proteinDescription": {
                "recommendedName": {"ecNumbers": [{"value": "1.1.1.1"}]},
                "alternativeNames": [{"ecNumbers": [{"value": "2.2.2.2"}]}],
            }
        }

        self.assertEqual(
            _extract_ec_numbers(entry),
            [{"id": "1.1.1.1", "name": ""}, {"id": "2.2.2.2", "name": ""}],
        )


class ExtractGoTermsTests(SimpleTestCase):
    def test_reads_go_id_name_and_aspect_and_ignores_other_databases(self):
        entry = {
            "uniProtKBCrossReferences": [
                {
                    "database": "GO",
                    "id": "GO:0005515",
                    "properties": [{"key": "GoTerm", "value": "F:protein binding"}],
                },
                {"database": "PDB", "id": "1ABC"},
            ]
        }

        self.assertEqual(
            _extract_go_terms(entry),
            [{"id": "GO:0005515", "name": "protein binding", "aspect": "F"}],
        )


class ExtractCrossReferencesTests(SimpleTestCase):
    def test_keeps_only_entries_with_database_and_id(self):
        entry = {
            "uniProtKBCrossReferences": [
                {"database": "PDB", "id": "1ABC"},
                {"database": "", "id": "x"},
                {"database": "GO", "id": ""},
            ]
        }

        self.assertEqual(_extract_cross_references(entry), [{"database": "PDB", "id": "1ABC"}])


class ExtractFeaturesTests(SimpleTestCase):
    def test_falls_back_to_start_when_end_is_missing(self):
        entry = {
            "features": [
                {
                    "type": "Domain",
                    "description": "Kinase domain",
                    "location": {"start": {"value": 10}, "end": {"value": 50}},
                },
                {
                    "type": "Site",
                    "description": "Active site",
                    "location": {"start": {"value": 100}},
                },
            ]
        }

        self.assertEqual(
            _extract_features(entry),
            [
                {"type": "Domain", "description": "Kinase domain", "start": 10, "end": 50},
                {"type": "Site", "description": "Active site", "start": 100, "end": 100},
            ],
        )

    def test_skips_features_without_a_start_position(self):
        entry = {"features": [{"type": "Domain", "location": {}}]}
        self.assertEqual(_extract_features(entry), [])


class ExtractKeywordsTests(SimpleTestCase):
    def test_drops_blank_and_missing_names(self):
        entry = {"keywords": [{"name": "Kinase"}, {"name": ""}, {}]}
        self.assertEqual(_extract_keywords(entry), ["Kinase"])


class ExtractSubcellularLocationsTests(SimpleTestCase):
    def test_dedupes_repeated_isoform_locations_preserving_order(self):
        entry = {
            "comments": [
                {
                    "commentType": "SUBCELLULAR LOCATION",
                    "subcellularLocations": [{"location": {"value": "Cell membrane"}}],
                },
                {
                    "commentType": "SUBCELLULAR LOCATION",
                    "subcellularLocations": [
                        {"location": {"value": "Cell membrane"}},
                        {"location": {"value": "Cytoplasm"}},
                    ],
                },
            ]
        }

        self.assertEqual(_extract_subcellular_locations(entry), ["Cell membrane", "Cytoplasm"])


class ExtractPublicationsTests(SimpleTestCase):
    def test_keeps_only_references_with_a_pubmed_id(self):
        entry = {
            "references": [
                {
                    "citation": {
                        "title": "A paper",
                        "citationCrossReferences": [{"database": "PubMed", "id": "12345"}],
                    }
                },
                {"citation": {"title": "No pubmed", "citationCrossReferences": []}},
            ]
        }

        self.assertEqual(_extract_publications(entry), [{"pubmed": "12345", "title": "A paper"}])


class BuildHumanProteinFieldsTests(SimpleTestCase):
    def test_combines_name_gene_and_comment_fields(self):
        entry = {
            "proteinDescription": {"recommendedName": {"fullName": {"value": "Test Protein"}}},
            "genes": [{"geneName": {"value": "TESTG"}}],
            "organism": {
                "scientificName": "Homo sapiens",
                "taxonId": 9606,
                "lineage": ["Eukaryota"],
            },
            "sequence": {"length": 100, "molWeight": 12345, "value": "MKT..."},
            "annotationScore": 5.0,
            "entryAudit": {"entryVersion": 3},
            "entryType": "UniProtKB reviewed (Swiss-Prot)",
            "comments": [{"commentType": "FUNCTION", "texts": [{"value": "Does a thing."}]}],
        }

        fields = _build_human_protein_fields(entry)

        self.assertEqual(fields["protein_name"], "Test Protein")
        self.assertEqual(fields["gene_symbol"], "TESTG")
        self.assertEqual(fields["organism_name"], "Homo sapiens")
        self.assertEqual(fields["taxon_id"], 9606)
        self.assertTrue(fields["is_reviewed"])
        self.assertEqual(fields["function_text"], "Does a thing.")
        self.assertEqual(fields["uniprot_raw"], entry)

    def test_defaults_organism_name_when_missing(self):
        fields = _build_human_protein_fields({})
        self.assertEqual(fields["organism_name"], "Homo sapiens")
        self.assertFalse(fields["is_reviewed"])
        self.assertEqual(fields["gene_symbol"], "")

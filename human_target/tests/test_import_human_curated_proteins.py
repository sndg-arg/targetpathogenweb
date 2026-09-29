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

from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.BioentryDbxref import BioentryDbxref

from human_target.models.HumanPathway import HumanPathway
from human_target.models.HumanProtein import HumanProtein
from human_target.models.HumanProteinPathway import HumanProteinPathway
from human_target.management.commands.import_human_curated_proteins import (
    Command,
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
    _parse_kgml,
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


class WriteUniprotDbxrefTests(TestCase):
    """`load_ligq_2_results`'s `_uniprot_map()` classifies ligand evidence as
    "direct" only when a `UnipSp`/`UnipTr` BioentryDbxref points from a
    Bioentry back at its own UniProt accession -- for human proteins the
    Bioentry.accession already *is* the UniProt accession, so this dbxref is
    the only signal that connects the two."""

    def _make_bioentry(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        return Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )

    def test_writes_unip_sp_dbxref_for_reviewed_entry(self):
        bioentry = self._make_bioentry("P10721")
        Command()._write_uniprot_dbxref(bioentry, "P10721", is_reviewed=True)

        dbxref = BioentryDbxref.objects.get(bioentry=bioentry)
        self.assertEqual(dbxref.dbxref.dbname, "UnipSp")
        self.assertEqual(dbxref.dbxref.accession, "P10721")

    def test_writes_unip_tr_dbxref_for_unreviewed_entry(self):
        bioentry = self._make_bioentry("A0A075B6I6")
        Command()._write_uniprot_dbxref(bioentry, "A0A075B6I6", is_reviewed=False)

        dbxref = BioentryDbxref.objects.get(bioentry=bioentry)
        self.assertEqual(dbxref.dbxref.dbname, "UnipTr")

    def test_idempotent_on_rerun(self):
        bioentry = self._make_bioentry("P10721")
        Command()._write_uniprot_dbxref(bioentry, "P10721", is_reviewed=True)
        Command()._write_uniprot_dbxref(bioentry, "P10721", is_reviewed=True)

        self.assertEqual(BioentryDbxref.objects.filter(bioentry=bioentry).count(), 1)


class LoadExpressionTests(TestCase):
    def _make_human_protein(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        return HumanProtein.objects.create(bioentry=bioentry, uniprot_accession=accession)

    def test_parses_rows_and_drops_unscored_ones(self):
        human_protein = self._make_human_protein("P10721")
        with tempfile.TemporaryDirectory() as tmp:
            protein_dir = Path(tmp)
            tsv_path = protein_dir / "Bgee-genex-heatmap.tsv"
            tsv_path.write_text(
                "gene_id\tgene_name\tanat_entity_name\tcell_type_name\texpression_score\t"
                "expression_score_confidence\tfdr\tdata_types_with_data\texpression_state\t"
                "expression_quality\tcluster_index\n"
                "ENSG1\tKIT\theart\t\t90.0\thigh\t0.002\tAffymetrix\texpressed\tgold\t0\n"
                "ENSG1\tKIT\tkidney\t\t\thigh\t0.002\tAffymetrix\texpressed\tsilver\t1\n",
                encoding="utf-8",
            )
            Command()._load_expression(protein_dir, "P10721", human_protein)

        human_protein.refresh_from_db()
        self.assertEqual(len(human_protein.expression_json), 1)
        row = human_protein.expression_json[0]
        self.assertEqual(row["tissue"], "heart")
        self.assertEqual(row["score"], 90.0)
        self.assertEqual(row["quality"], "gold")

    def test_missing_file_is_skipped_without_error(self):
        human_protein = self._make_human_protein("P10721")
        with tempfile.TemporaryDirectory() as tmp:
            Command()._load_expression(Path(tmp), "P10721", human_protein)

        human_protein.refresh_from_db()
        self.assertEqual(human_protein.expression_json, [])


_SAMPLE_KGML = """<?xml version="1.0"?>
<pathway name="path:hsa04010" org="hsa" number="04010" title="MAPK signaling pathway">
  <entry id="1" name="hsa:5594" type="gene">
    <graphics name="MAPK1, ERK2" type="rectangle"/>
  </entry>
  <entry id="2" name="hsa:5595" type="gene">
    <graphics name="MAPK3, ERK1" type="rectangle"/>
  </entry>
  <entry id="3" name="cpd:C00000" type="compound">
    <graphics name="a compound"/>
  </entry>
  <entry id="4" name="hsa:9999" type="gene">
    <graphics name="ISOLATED" type="rectangle"/>
  </entry>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation"/>
  </relation>
</pathway>
"""


class ParseKgmlTests(SimpleTestCase):
    def test_keeps_only_gene_ortholog_nodes_that_participate_in_a_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            kgml_path = Path(tmp) / "hsa04010.kgml"
            kgml_path.write_text(_SAMPLE_KGML, encoding="utf-8")

            graph = _parse_kgml(kgml_path)

        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertEqual(node_ids, {"1", "2"})
        self.assertEqual(
            graph["edges"], [{"source": "1", "target": "2", "subtypes": ["activation"]}]
        )
        labels = {node["id"]: node["label"] for node in graph["nodes"]}
        self.assertEqual(labels["1"], "MAPK1")

    def test_isolated_and_compound_entries_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            kgml_path = Path(tmp) / "hsa04010.kgml"
            kgml_path.write_text(_SAMPLE_KGML, encoding="utf-8")

            graph = _parse_kgml(kgml_path)

        node_ids = {node["id"] for node in graph["nodes"]}
        self.assertNotIn("3", node_ids)
        self.assertNotIn("4", node_ids)


class LoadPathwaysTests(TestCase):
    def _make_human_protein(self, accession, gene_id=""):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        cross_refs = [{"database": "GeneID", "id": gene_id}] if gene_id else []
        return HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession=accession,
            cross_references_raw=cross_refs,
        )

    def _write_kgml_tree(self, protein_dir):
        kegg_dir = protein_dir / "kegg_kgml"
        kegg_dir.mkdir()
        (kegg_dir / "index.json").write_text(
            json.dumps(
                [
                    {
                        "id": "hsa04010",
                        "file": "hsa04010.kgml",
                        "title": "MAPK signaling pathway",
                        "entries": 2,
                        "relations": 1,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (kegg_dir / "hsa04010.kgml").write_text(_SAMPLE_KGML, encoding="utf-8")

    def test_creates_pathway_and_link_with_highlighted_node(self):
        human_protein = self._make_human_protein("P10721", gene_id="5594")
        with tempfile.TemporaryDirectory() as tmp:
            protein_dir = Path(tmp)
            self._write_kgml_tree(protein_dir)
            Command()._load_pathways(protein_dir, "P10721", human_protein)

        pathway = HumanPathway.objects.get(kegg_id="hsa04010")
        self.assertEqual(pathway.title, "MAPK signaling pathway")
        link = HumanProteinPathway.objects.get(human_protein=human_protein, pathway=pathway)
        self.assertEqual(link.highlighted_node_id, "1")

    def test_missing_index_is_skipped_without_error(self):
        human_protein = self._make_human_protein("P10721")
        with tempfile.TemporaryDirectory() as tmp:
            Command()._load_pathways(Path(tmp), "P10721", human_protein)

        self.assertEqual(HumanProteinPathway.objects.filter(human_protein=human_protein).count(), 0)

    def test_sharing_a_pathway_reuses_the_same_pathway_row(self):
        first_protein = self._make_human_protein("P10721", gene_id="5594")
        second_protein = self._make_human_protein("P10722", gene_id="5595")
        with tempfile.TemporaryDirectory() as tmp:
            protein_dir = Path(tmp)
            self._write_kgml_tree(protein_dir)
            Command()._load_pathways(protein_dir, "P10721", first_protein)
            Command()._load_pathways(protein_dir, "P10722", second_protein)

        self.assertEqual(HumanPathway.objects.filter(kegg_id="hsa04010").count(), 1)
        second_link = HumanProteinPathway.objects.get(human_protein=second_protein)
        self.assertEqual(second_link.highlighted_node_id, "2")

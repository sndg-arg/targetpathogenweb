from types import SimpleNamespace

from django.test import SimpleTestCase

from human_target.services.human_dossier import (
    build_human_dossier,
    build_keyword_groups,
    build_pdb_coverage,
    build_pharmacology,
    build_publications,
    build_variants,
    compartments_for,
    disease_variant_counts,
)

RAW = {
    "uniProtKBCrossReferences": [
        {
            "database": "DrugBank",
            "id": "DB00619",
            "properties": [{"key": "GenericName", "value": "Imatinib"}],
        },
        {
            "database": "DrugBank",
            "id": "DB01268",
            "properties": [{"key": "GenericName", "value": "Sunitinib"}],
        },
        {
            "database": "ChEMBL",
            "id": "CHEMBL1936",
            "properties": [{"key": "Description", "value": "-"}],
        },
        {"database": "PDB", "id": "1T46", "properties": [{"key": "Chains", "value": "A=1-50"}]},
        {"database": "PDB", "id": "4U0I", "properties": [{"key": "Chains", "value": "A/B=26-100"}]},
    ],
    "features": [
        {
            "type": "Natural variant",
            "location": {"start": {"value": 816}, "end": {"value": 816}},
            "description": "in GIST and MASTSYS; somatic mutation",
            "alternativeSequence": {"originalSequence": "D", "alternativeSequences": ["V"]},
        },
        {
            "type": "Natural variant",
            "location": {"start": {"value": 557}, "end": {"value": 558}},
            "description": "in GIST",
            "alternativeSequence": {"originalSequence": "WK", "alternativeSequences": []},
        },
    ],
    "references": [
        {
            "citation": {
                "title": "Old.",
                "publicationDate": "1987",
                "journal": "EMBO J.",
                "authors": ["Yarden Y.", "B"],
                "citationCrossReferences": [{"database": "PubMed", "id": "1"}],
            }
        },
        {
            "citation": {
                "title": "New",
                "publicationDate": "2014",
                "journal": "Blood",
                "authors": ["Solo A."],
                "citationCrossReferences": [{"database": "PubMed", "id": "2"}],
            }
        },
        {"citation": {"title": "No PubMed"}},
    ],
    "keywords": [
        {"category": "Ligand", "name": "ATP-binding"},
        {"category": "Molecular function", "name": "Kinase"},
        {"category": "Ligand", "name": "Magnesium"},
    ],
}


class HumanDossierTests(SimpleTestCase):
    def test_pharmacology_lists_drugbank_compounds_and_resource_links(self):
        pharma = build_pharmacology(RAW)
        self.assertEqual([d["name"] for d in pharma["drugs"]], ["Imatinib", "Sunitinib"])
        self.assertEqual([link["label"] for link in pharma["links"]], ["ChEMBL"])
        self.assertTrue(pharma["has_pharmacology"])
        self.assertFalse(build_pharmacology({})["has_pharmacology"])

    def test_variants_carry_residue_change_and_diseases(self):
        variants = build_variants(RAW, 976)
        self.assertEqual([v["label"] for v in variants], ["D816V", "WK557del"])
        self.assertEqual(variants[0]["diseases"], ["GIST", "MASTSYS"])
        self.assertEqual(disease_variant_counts(variants), {"GIST": 2, "MASTSYS": 1})

    def test_pdb_coverage_counts_structures_per_stretch(self):
        coverage = build_pdb_coverage(RAW, 100, bins=10)
        self.assertEqual(
            [cell["count"] for cell in coverage["cells"]], [1, 1, 2, 2, 2, 1, 1, 1, 1, 1]
        )
        self.assertEqual((coverage["structures"], coverage["peak"]), (2, 2))
        self.assertIsNone(build_pdb_coverage({}, 100))

    def test_publications_newest_first_with_first_author(self):
        pubs = build_publications(RAW)
        self.assertEqual(pubs["total"], 2)
        self.assertEqual([p["year"] for p in pubs["items"]], ["2014", "1987"])
        self.assertEqual(pubs["items"][1]["authors"], "Yarden Y. et al.")

    def test_keywords_grouped_in_uniprot_category_order(self):
        groups = build_keyword_groups(RAW)
        self.assertEqual(
            groups,
            [
                {"category": "Molecular function", "keywords": ["Kinase"]},
                {"category": "Ligand", "keywords": ["ATP-binding", "Magnesium"]},
            ],
        )

    def test_locations_light_up_cell_compartments(self):
        self.assertEqual(
            compartments_for(
                ["Cell membrane", "Cytoplasm", "Secreted", "Golgi apparatus membrane"]
            ),
            ["membrane", "cytoplasm", "secreted", "golgi"],
        )

    def test_dossier_tolerates_a_protein_without_raw_entry(self):
        protein = SimpleNamespace(
            uniprot_raw=None, sequence_length=None, sequence="", subcellular_locations=[]
        )
        dossier = build_human_dossier(protein)
        self.assertEqual(dossier["variants"], [])
        self.assertIsNone(dossier["pdb_coverage"])


class GlanceTests(SimpleTestCase):
    def test_one_tile_per_kind_of_evidence_that_exists(self):
        from human_target.services.human_dossier import build_glance

        dossier = {
            "pharmacology": {"drugs": [{"id": "DB1", "name": "A"}]},
            "disease_variant_counts": {"GIST": 3},
        }
        tiles = build_glance(
            dossier,
            {"diseases": [{"name": "GIST"}]},
            {"sub_tabs": [{"key": "alphafold", "count": 1}, {"key": "xray", "count": 4}]},
            {"total": 0},
            {"has_expression": True, "tau": 0.2, "specificity_label": "Broadly expressed"},
            {"pathways": []},
        )
        self.assertEqual(
            [(t["label"], t["value"]) for t in tiles],
            [
                ("DrugBank compounds", 1),
                ("Diseases", 1),
                ("3D structures", 5),
                ("Tissue specificity", "0.20"),
            ],
        )
        self.assertEqual(tiles[1]["note"], "3 disease variants")
        self.assertEqual(tiles[2]["note"], "4 experimental")


class AssessmentTests(SimpleTestCase):
    def test_reads_each_question_off_the_evidence(self):
        from human_target.services.human_dossier import build_assessment

        dossier = {
            "pharmacology": {"drugs": [{"id": "DB1", "name": "Imatinib"}]},
            "disease_variant_counts": {},
            "pdb_coverage": {"covered_percent": 80},
            "compartments": ["membrane", "cytoplasm"],
        }
        rows = build_assessment(
            dossier,
            {"diseases": [{"acronym": "GIST"}]},
            {"sub_tabs": [{"key": "xray", "count": 3, "entries": []}]},
            {"total": 0},
            {
                "has_expression": True,
                "tau": 0.1,
                "peak": {"tissue": "testis"},
                "expressed_count": 90,
                "tissue_count": 100,
            },
        )
        by_label = {row["label"]: row for row in rows}
        self.assertEqual(by_label["Clinical precedent"]["tone"], "strong")
        self.assertEqual(by_label["Genetic evidence"]["tone"], "moderate")
        self.assertIn("~80%", by_label["Structure"]["finding"])
        self.assertEqual(by_label["Ligandability"]["status"], "No ligand evidence")
        self.assertEqual(by_label["Tissue selectivity"]["status"], "Broadly expressed")
        self.assertEqual(by_label["Accessibility"]["status"], "Extracellular access")

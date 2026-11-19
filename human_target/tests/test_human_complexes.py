import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_complexes_bulk import (
    canonical_accession,
    parse_corum,
)
from human_target.models.HumanComplex import HumanComplex
from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_complex_summary import build_human_complex_context

HEADER = (
    "complex_id\tcomplex_name\tsynonyms\torganism\tcell_line\tpmid\tcomment_complex\t"
    "comment_disease\tsubunits_uniprot_id\tsubunits_gene_name\tsubunits_protein_name\t"
    "purification_methods\tfunctions_go_id\tfunctions_go_name"
)
ROWS = [
    '1\tBCL6-HDAC4 complex\tNone\tHuman\tU2OS\t11929873\t"Repression\nacross lines."\tNone\t'
    "P41182;P56524-2;Q00000\tBCL6;HDAC4;FAKE\tB-cell lymphoma 6 protein;Histone deacetylase 4;Fake\t"
    "MI:0007:anti tag coimmunoprecipitation;MI:0007:anti tag coimmunoprecipitation\t"
    "GO:0006355;None\tregulation of transcription;None",
    "2\tMouse thing\tNone\tMouse\tNone\tNone\tNone\tNone\tP41182\tBcl6\tx\tNone\tNone\tNone",
]
CORUM_TEXT = "\n".join([HEADER, *ROWS]) + "\n"


class ParseCorumTests(SimpleTestCase):
    def test_keeps_human_complexes_with_aligned_subunits(self):
        complexes = parse_corum(CORUM_TEXT)
        self.assertEqual([c["corum_id"] for c in complexes], [1])
        cx = complexes[0]
        self.assertEqual(
            cx["subunits"][1],
            {"accession": "P56524-2", "gene": "HDAC4", "name": "Histone deacetylase 4"},
        )
        self.assertEqual(cx["purification_methods"], ["anti tag coimmunoprecipitation"])
        self.assertEqual(
            cx["go_terms"], [{"id": "GO:0006355", "name": "regulation of transcription"}]
        )
        self.assertEqual(cx["synonyms"], "")
        self.assertEqual(cx["comment"], "Repression\nacross lines.")

    def test_isoforms_link_to_the_canonical_protein(self):
        self.assertEqual(canonical_accession("p56524-2"), "P56524")


class LoadHumanComplexesTests(TestCase):
    def _protein(self, accession):
        biodatabase, _ = Biodatabase.objects.get_or_create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        return HumanProtein.objects.create(bioentry=bioentry, uniprot_accession=accession)

    def test_loads_links_and_builds_the_page_context(self):
        bcl6 = self._protein("P41182")
        self._protein("P56524")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(CORUM_TEXT)
        call_command("load_human_complexes_bulk", file=fh.name, stdout=StringIO())
        # Re-running replaces instead of duplicating.
        call_command("load_human_complexes_bulk", file=fh.name, stdout=StringIO())
        self.assertEqual(HumanComplex.objects.count(), 1)

        context = build_human_complex_context(bcl6)
        self.assertTrue(context["has_complexes"])
        subunits = context["complexes"][0]["subunits"]
        self.assertEqual(
            [(s["label"], s["is_self"], s["is_known"]) for s in subunits],
            [("BCL6", True, False), ("HDAC4", False, True), ("FAKE", False, False)],
        )

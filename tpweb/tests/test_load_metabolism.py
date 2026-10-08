"""Tests for load_metabolism.py's pure SBML/SIF parsing helpers -- these
back the metabolic pathway import (see CLAUDE.md's "Metabolic pathway
integration" section), so a regression here silently corrupts reaction
centrality/chokepoint data rather than raising, making it worth pinning
down with real XML fixtures instead of trusting it by inspection.
"""

import os
import tempfile
import xml.etree.ElementTree as ET

from django.test import SimpleTestCase

from tpweb.management.commands.load_metabolism import (
    SBML_NS,
    _annotation_resources,
    _clean,
    _count_isoenzymes,
    _decode_sbml_id,
    _is_currency_species,
    _species_participants,
    _tag,
    _walk_gpr,
    parse_network_sif,
)


def _gene_ref(gp_id):
    elem = ET.Element("geneProductRef")
    elem.set(f"{{{SBML_NS['fbc']}}}geneProduct", gp_id)
    return elem


GENE_PRODUCTS = {
    "gp1": {"locus_tag": "geneA", "gene_name": "gene A"},
    "gp2": {"locus_tag": "geneB", "gene_name": "gene B"},
}


class TagTests(SimpleTestCase):
    def test_strips_namespace_prefix(self):
        elem = ET.Element(f"{{{SBML_NS['sbml']}}}reaction")
        self.assertEqual(_tag(elem), "reaction")

    def test_leaves_unnamespaced_tag_untouched(self):
        elem = ET.Element("reaction")
        self.assertEqual(_tag(elem), "reaction")


class DecodeSbmlIdTests(SimpleTestCase):
    def test_decodes_double_underscore_ascii_escapes(self):
        # 45 is ASCII '-'
        self.assertEqual(_decode_sbml_id("Compound__45__cytosol"), "Compound-cytosol")

    def test_leaves_plain_ids_untouched(self):
        self.assertEqual(_decode_sbml_id("ATP_c"), "ATP_c")


class IsCurrencySpeciesTests(SimpleTestCase):
    def test_false_when_currency_set_is_empty(self):
        self.assertFalse(_is_currency_species("ATP_c", "c", set()))

    def test_true_for_compartment_suffixed_match(self):
        self.assertTrue(_is_currency_species("ATP_c", "c", {"ATP"}))

    def test_false_when_compartment_does_not_match(self):
        self.assertFalse(_is_currency_species("NADH_m", "c", {"ATP"}))


class CleanTests(SimpleTestCase):
    def test_returns_none_for_missing_markers(self):
        self.assertIsNone(_clean(None))
        self.assertIsNone(_clean("nan"))
        self.assertIsNone(_clean(""))

    def test_strips_whitespace(self):
        self.assertEqual(_clean("  Glucose  "), "Glucose")


class ParseNetworkSifTests(SimpleTestCase):
    def _parse(self, content):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sif", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            path = f.name
        try:
            return parse_network_sif(path)
        finally:
            os.unlink(path)

    def test_reads_tab_separated_source_target_pairs(self):
        edges = self._parse("RXN-1\tprecedes\tRXN-2\nRXN-2\tprecedes\tRXN-3\n")
        self.assertEqual(edges, [("RXN-1", "RXN-2"), ("RXN-2", "RXN-3")])

    def test_falls_back_to_whitespace_split(self):
        edges = self._parse("RXN-1 precedes RXN-2\n")
        self.assertEqual(edges, [("RXN-1", "RXN-2")])

    def test_skips_lines_without_exactly_three_columns(self):
        edges = self._parse("not-enough-columns\nRXN-1\tprecedes\tRXN-2\n")
        self.assertEqual(edges, [("RXN-1", "RXN-2")])


class WalkGprTests(SimpleTestCase):
    def test_leaf_gene_product_ref_resolves_locus_tag(self):
        genes, expr = _walk_gpr(_gene_ref("gp1"), GENE_PRODUCTS)
        self.assertEqual(genes, {"geneA"})
        self.assertEqual(expr, "geneA")

    def test_unknown_gene_product_falls_back_to_raw_id(self):
        genes, expr = _walk_gpr(_gene_ref("unknown_gp"), GENE_PRODUCTS)
        self.assertEqual(genes, {"unknown_gp"})
        self.assertEqual(expr, "unknown_gp")

    def test_or_joins_branches_as_isoenzyme_alternatives(self):
        or_elem = ET.Element("or")
        or_elem.append(_gene_ref("gp1"))
        or_elem.append(_gene_ref("gp2"))

        genes, expr = _walk_gpr(or_elem, GENE_PRODUCTS)

        self.assertEqual(genes, {"geneA", "geneB"})
        self.assertEqual(expr, "(geneA or geneB)")

    def test_and_joins_branches_as_obligate_complex(self):
        and_elem = ET.Element("and")
        and_elem.append(_gene_ref("gp1"))
        and_elem.append(_gene_ref("gp2"))

        genes, expr = _walk_gpr(and_elem, GENE_PRODUCTS)

        self.assertEqual(genes, {"geneA", "geneB"})
        self.assertEqual(expr, "(geneA and geneB)")


class CountIsoenzymesTests(SimpleTestCase):
    def test_none_root_has_no_isoenzymes(self):
        self.assertEqual(_count_isoenzymes(None), 0)

    def test_top_level_or_counts_each_branch(self):
        or_elem = ET.Element("or")
        or_elem.append(_gene_ref("gp1"))
        or_elem.append(_gene_ref("gp2"))
        self.assertEqual(_count_isoenzymes(or_elem), 2)

    def test_single_gene_ref_is_one_isoenzyme(self):
        self.assertEqual(_count_isoenzymes(_gene_ref("gp1")), 1)

    def test_top_level_and_is_one_isoenzyme(self):
        and_elem = ET.Element("and")
        and_elem.append(_gene_ref("gp1"))
        and_elem.append(_gene_ref("gp2"))
        self.assertEqual(_count_isoenzymes(and_elem), 1)


class SpeciesParticipantsTests(SimpleTestCase):
    def test_reads_species_id_and_stoichiometry(self):
        list_elem = ET.Element("listOfReactants")
        ref1 = ET.SubElement(list_elem, f"{{{SBML_NS['sbml']}}}speciesReference")
        ref1.set("species", "M_atp_c")
        ref1.set("stoichiometry", "2")
        ref2 = ET.SubElement(list_elem, f"{{{SBML_NS['sbml']}}}speciesReference")
        ref2.set("species", "M_h2o_c")

        participants = _species_participants(list_elem)

        self.assertEqual(participants, [("M_atp_c", 2.0), ("M_h2o_c", 1.0)])

    def test_skips_references_without_a_species_id(self):
        list_elem = ET.Element("listOfReactants")
        ref = ET.SubElement(list_elem, f"{{{SBML_NS['sbml']}}}speciesReference")
        ref.set("stoichiometry", "1")

        self.assertEqual(_species_participants(list_elem), [])


class AnnotationResourcesTests(SimpleTestCase):
    def test_yields_rdf_li_resource_uris(self):
        root = ET.Element("annotation")
        li = ET.SubElement(root, f"{{{SBML_NS['rdf']}}}li")
        li.set(f"{{{SBML_NS['rdf']}}}resource", "http://identifiers.org/ec-code/1.1.1.1")

        self.assertEqual(
            list(_annotation_resources(root)), ["http://identifiers.org/ec-code/1.1.1.1"]
        )

    def test_no_li_elements_yields_nothing(self):
        root = ET.Element("annotation")
        self.assertEqual(list(_annotation_resources(root)), [])

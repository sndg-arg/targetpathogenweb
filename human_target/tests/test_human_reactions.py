import json
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_reactions_bulk import parse_recon3d
from human_target.models.HumanProtein import HumanProtein
from human_target.models.HumanReaction import HumanReaction
from human_target.services.human_reaction_summary import build_human_reaction_context

MODEL = {
    "compartments": {"c": "cytosol", "m": "mitochondria"},
    "metabolites": [
        {"id": "atp_c", "name": "ATP", "compartment": "c"},
        {"id": "glc_c", "name": "Glucose", "compartment": "c"},
        {"id": "g6p_c", "name": "Glucose 6-phosphate", "compartment": "c"},
        {"id": "adp_c", "name": "ADP", "compartment": "c"},
        {"id": "pyr_c", "name": "Pyruvate", "compartment": "c"},
        {"id": "pyr_m", "name": "Pyruvate", "compartment": "m"},
    ],
    "reactions": [
        {
            "id": "HEX1",
            "name": "Hexokinase",
            "metabolites": {"atp_c": -1, "glc_c": -1, "g6p_c": 1, "adp_c": 1},
            "lower_bound": 0,
            "upper_bound": 1000,
            "gene_reaction_rule": "3098_AT1 or 3099_AT1",
            "subsystem": "Glycolysis/gluconeogenesis",
        },
        {
            "id": "PYRt2m",
            "name": "Pyruvate transport",
            "metabolites": {"pyr_c": -2, "pyr_m": 2},
            "lower_bound": -1000,
            "upper_bound": 1000,
            "gene_reaction_rule": "(3098_AT1)",
            "subsystem": "Transport, mitochondrial",
        },
        {"id": "EX_glc", "metabolites": {"glc_c": -1}, "gene_reaction_rule": ""},
    ],
}


class ParseRecon3DTests(SimpleTestCase):
    def test_renders_equations_and_maps_genes(self):
        reactions, genes = parse_recon3d(MODEL)
        by_id = {row["bigg_id"]: row for row in reactions}
        self.assertEqual(set(by_id), {"HEX1", "PYRt2m"})
        self.assertEqual(by_id["HEX1"]["equation"], "ATP + Glucose → Glucose 6-phosphate + ADP")
        self.assertEqual(by_id["PYRt2m"]["equation"], "2 Pyruvate [c] ⇌ 2 Pyruvate [m]")
        self.assertTrue(by_id["PYRt2m"]["reversible"])
        self.assertEqual(by_id["PYRt2m"]["compartments"], "cytosol, mitochondria")
        self.assertEqual(genes["3098"], {"HEX1", "PYRt2m"})


class LoadHumanReactionsTests(TestCase):
    def test_links_proteins_by_gene_id(self):
        biodatabase, _ = Biodatabase.objects.get_or_create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name="P19367", accession="P19367", identifier="P19367"
        )
        protein = HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession="P19367",
            cross_references_raw=[{"database": "GeneID", "id": "3098"}],
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(MODEL, fh)
        call_command("load_human_reactions_bulk", file=fh.name, stdout=StringIO())
        call_command("load_human_reactions_bulk", file=fh.name, stdout=StringIO())
        self.assertEqual(HumanReaction.objects.count(), 2)

        context = build_human_reaction_context(protein)
        self.assertEqual(context["total"], 2)
        self.assertEqual(
            context["subsystems"],
            [("Glycolysis/gluconeogenesis", 1), ("Transport, mitochondrial", 1)],
        )

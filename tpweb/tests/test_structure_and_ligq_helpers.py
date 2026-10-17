"""Tests for a couple of @staticmethod helpers on management Command
classes that don't need self/DB and can be called directly off the class.
"""

import os
import tempfile
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase

from tpweb.management.commands.load_af_model import Command as LoadAfModelCommand
from tpweb.management.commands.load_ligq_2_results import HET_DENYLIST
from tpweb.management.commands.load_ligq_2_results import Command as LoadLigqResultsCommand


class SanitizeCifTests(SimpleTestCase):
    def test_returns_original_path_when_no_apostrophe(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", delete=False, encoding="utf-8"
        ) as f:
            f.write("_chem_comp.name  ADENOSINE-TRIPHOSPHATE\n")
            path = f.name
        try:
            result = LoadAfModelCommand._sanitize_cif(path)
            self.assertEqual(result, path)
        finally:
            os.unlink(path)

    def test_replaces_apostrophes_in_a_new_temp_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", delete=False, encoding="utf-8"
        ) as f:
            f.write('_chem_comp.name  "ADENOSINE-5\'-TRIPHOSPHATE"\n')
            path = f.name
        result = None
        try:
            result = LoadAfModelCommand._sanitize_cif(path)
            self.assertNotEqual(result, path)
            with open(result, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("'", content)
            self.assertIn("*", content)
        finally:
            os.unlink(path)
            if result and result != path:
                os.unlink(result)


class FormatKnownNotesTests(SimpleTestCase):
    def test_joins_present_fields_and_skips_blank_ones(self):
        row = {
            "search_type": "direct",
            "source": "ChEMBL",
            "mechanism": "",
            "activity_comment": None,
            "curation_method": "manual",
            "binding_sites": "",
        }

        self.assertEqual(
            LoadLigqResultsCommand._format_known_notes(row),
            "LigQ direct | source=ChEMBL | curation=manual",
        )

    def test_empty_row_returns_empty_string(self):
        self.assertEqual(LoadLigqResultsCommand._format_known_notes({}), "")


class FormatZincNotesTests(SimpleTestCase):
    def test_joins_present_fields(self):
        row = {"search_type": "similarity", "query_id": "Q1", "sseqid": "P12345"}

        self.assertEqual(
            LoadLigqResultsCommand._format_zinc_notes(row),
            "LigQ similarity | query=Q1 | homolog=P12345",
        )

    def test_empty_row_returns_empty_string(self):
        self.assertEqual(LoadLigqResultsCommand._format_zinc_notes({}), "")


class HetDenylistTests(SimpleTestCase):
    """Crystallization additives found leaking into human-protein ligand
    evidence (A0A075B6I6's PDB-homolog table) that the denylist didn't
    cover: uranyl phasing ion, azide, peroxide, cryoprotectants, detergents."""

    def test_covers_newly_found_crystallization_artifacts(self):
        for code in ("IUM", "AZI", "PEO", "PER", "TMO", "LDA", "LMT", "ETX"):
            self.assertIn(code, HET_DENYLIST)

    def test_still_covers_original_entries(self):
        for code in ("HOH", "ALA", "GOL", "SO4"):
            self.assertIn(code, HET_DENYLIST)


class CollectTablesPreCapTests(SimpleTestCase):
    """The read-time pre-cap (2x the final per-protein limit, applied before
    concat to keep memory bounded) must also protect direct evidence, or a
    protein's own real hits never even reach the final top-N cut."""

    def test_pre_cap_keeps_a_direct_row_ahead_of_higher_pchembl_homolog_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            prot_dir = Path(tmp) / "search_results" / "P10721"
            prot_dir.mkdir(parents=True)
            rows = ["search_type\tuniprot_id\tchem_comp_id\tsource\tpchembl\tsmiles"]
            rows.append("sequence\tP10721\tDIRECT1\tchembl\t6.0\tC")
            for i in range(5):
                rows.append(f"sequence\tP07333\tHOMOLOG{i}\tchembl\t9.{i}\tC")
            (prot_dir / "known_ligands.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

            known_df, _ = LoadLigqResultsCommand()._collect_tables(
                Path(tmp),
                None,
                max_known_per_protein=2,
                max_pdb_per_protein=0,
                max_zinc_per_protein=50,
                min_tanimoto=0.5,
            )

        self.assertIn("DIRECT1", set(known_df["chem_comp_id"]))


class TopNByPchemblTests(SimpleTestCase):
    """A protein's own (direct) evidence must survive the per-protein top-N
    cut even when homolog-transferred rows have higher pchembl -- otherwise
    direct evidence can be crowded out entirely (seen on P10721/KIT: 1462
    real self-matched ChEMBL rows, almost none of them in the top 100 by
    raw potency alone)."""

    def test_direct_rows_are_kept_ahead_of_higher_pchembl_homolog_rows(self):
        df = pd.DataFrame(
            {
                "_locustag": ["P10721"] * 4,
                "uniprot_id": ["P10721", "P10721", "P07333", "P07333"],
                "pchembl": [6.0, 6.5, 10.0, 9.5],
                "chem_comp_id": ["A", "B", "C", "D"],
            }
        )

        top2 = LoadLigqResultsCommand._top_n_by_pchembl(df, 2)

        self.assertEqual(set(top2["chem_comp_id"]), {"A", "B"})

    def test_backfills_with_best_homolog_rows_once_direct_rows_are_exhausted(self):
        df = pd.DataFrame(
            {
                "_locustag": ["P10721"] * 3,
                "uniprot_id": ["P10721", "P07333", "P04049"],
                "pchembl": [6.0, 10.0, 9.5],
                "chem_comp_id": ["A", "C", "D"],
            }
        )

        top2 = LoadLigqResultsCommand._top_n_by_pchembl(df, 2)

        self.assertEqual(set(top2["chem_comp_id"]), {"A", "C"})

    def test_groups_independently_per_locustag(self):
        df = pd.DataFrame(
            {
                "_locustag": ["P10721", "P10721", "O00116", "O00116"],
                "uniprot_id": ["P07333", "P04049", "O00116", "P35318"],
                "pchembl": [10.0, 9.0, 5.0, 8.0],
                "chem_comp_id": ["A", "B", "C", "D"],
            }
        )

        top1 = LoadLigqResultsCommand._top_n_by_pchembl(df, 1)

        kept = set(top1["chem_comp_id"])
        self.assertIn("A", kept)  # best for P10721 (no direct row available)
        self.assertIn("C", kept)  # O00116's own direct row, despite lower pchembl

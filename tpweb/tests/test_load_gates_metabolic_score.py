"""Tests for load_gates_metabolic_score.py's dedupe_strain_rows -- the
combined pan-genome mapping CSV can have more than one row map to the same
real locus tag (redundant/paralogous pan-gene splits resolving to the same
confirmed ortholog), so getting the "which row wins" rule wrong would
silently load the wrong S_gene/reaction_support/quadrant/priority onto a
protein instead of raising.
"""

import pandas as pd
from django.test import SimpleTestCase

from tpweb.management.commands.load_gates_metabolic_score import (
    dedupe_strain_rows,
    duplicate_locus_tags,
)


def _row(locus_tag, status, s_gene, reaction_support, n_reactions=1, quadrant="", priority=""):
    return {
        "KP13_id_mapeado": locus_tag,
        "KP13_estado": status,
        "S_gene": s_gene,
        "reaction_support": reaction_support,
        "n_reactions": n_reactions,
        "quadrant": quadrant,
        "priority": priority,
    }


class DedupeStrainRowsTests(SimpleTestCase):
    def test_drops_unmapped_rows(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.5, 0.7),
                _row(None, "no_mapeado", 0, 0),
            ]
        )

        result = dedupe_strain_rows(df, "KP13_id_mapeado", "KP13_estado")

        self.assertEqual(list(result["KP13_id_mapeado"]), ["KP13_01"])

    def test_keeps_paralog_substitute_status_rows(self):
        # "confirmado_sustituto_paralogo" and similar are still real mappings
        # -- only the literal "no_mapeado" sentinel means there's no gene.
        df = pd.DataFrame([_row("KP13_01", "confirmado_sustituto_paralogo", 0.3, 0.6)])

        result = dedupe_strain_rows(df, "KP13_id_mapeado", "KP13_estado")

        self.assertEqual(len(result), 1)

    def test_duplicate_locus_tag_keeps_highest_reaction_support(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.2825, 0.5, quadrant="Low reaction / Low gene"),
                _row("KP13_01", "confirmado", 0, 0.9, quadrant="High reaction / High gene"),
            ]
        )

        result = dedupe_strain_rows(df, "KP13_id_mapeado", "KP13_estado")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["reaction_support"], 0.9)
        self.assertEqual(result.iloc[0]["quadrant"], "High reaction / High gene")

    def test_duplicate_locus_tag_ties_break_on_highest_s_gene(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.2825, 0.7),
                _row("KP13_01", "confirmado", 0, 0.7),
            ]
        )

        result = dedupe_strain_rows(df, "KP13_id_mapeado", "KP13_estado")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["S_gene"], 0.2825)

    def test_distinct_locus_tags_are_all_kept(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.5, 0.7),
                _row("KP13_02", "confirmado", 0.3, 0.4),
            ]
        )

        result = dedupe_strain_rows(df, "KP13_id_mapeado", "KP13_estado")

        self.assertEqual(sorted(result["KP13_id_mapeado"]), ["KP13_01", "KP13_02"])


class DuplicateLocusTagsTests(SimpleTestCase):
    def test_no_duplicates_returns_empty(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.5, 0.7),
                _row("KP13_02", "confirmado", 0.3, 0.4),
            ]
        )

        self.assertEqual(duplicate_locus_tags(df, "KP13_id_mapeado", "KP13_estado"), [])

    def test_lists_only_the_locus_tags_that_collapsed(self):
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.2825, 0.5),
                _row("KP13_01", "confirmado", 0, 0.9),
                _row("KP13_02", "confirmado", 0.3, 0.4),
            ]
        )

        self.assertEqual(duplicate_locus_tags(df, "KP13_id_mapeado", "KP13_estado"), ["KP13_01"])

    def test_ignores_no_mapeado_rows_when_finding_duplicates(self):
        # Same locus tag appears twice, but one row is "no_mapeado" -- only
        # the mapped row counts, so this isn't a real collapse.
        df = pd.DataFrame(
            [
                _row("KP13_01", "confirmado", 0.5, 0.7),
                _row("KP13_01", "no_mapeado", 0, 0),
            ]
        )

        self.assertEqual(duplicate_locus_tags(df, "KP13_id_mapeado", "KP13_estado"), [])

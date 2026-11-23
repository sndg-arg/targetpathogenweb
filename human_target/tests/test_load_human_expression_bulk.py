import gzip
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_expression_bulk import (
    _ensembl_gene_ids,
    _expression_row,
)
from human_target.models.HumanProtein import HumanProtein

_BGEE_TSV = (
    'Gene ID\t"Gene name"\tAnatomical entity ID\t"Anatomical entity name"\tExpression\t'
    "Call quality\tFDR\tExpression score\tExpression rank\n"
    'ENSG00000146648\t"EGFR"\tUBERON:0002107\t"liver"\tpresent\tgold quality\t0.001\t88.5\t1200\n'
    'ENSG00000146648\t"EGFR"\tUBERON:0000955\t"brain"\tabsent\tsilver quality\t0.3\t12.0\t3.1e4\n'
    'ENSG00000999999\t"OTHER"\tUBERON:0002107\t"liver"\tpresent\tgold quality\t0.001\t50.0\t1\n'
)


class EnsemblGeneIdsTests(SimpleTestCase):
    def test_reads_bgee_xref_and_ensembl_gene_id_property_without_version(self):
        xrefs = [
            {"database": "Bgee", "id": "ENSG00000146648"},
            {
                "database": "Ensembl",
                "id": "ENST00000275493.7",
                "properties": [
                    {"key": "ProteinId", "value": "ENSP00000275493.2"},
                    {"key": "GeneId", "value": "ENSG00000146648.22"},
                ],
            },
            {"database": "GeneID", "id": "1956"},
        ]
        self.assertEqual(_ensembl_gene_ids(xrefs), {"ENSG00000146648"})

    def test_no_xrefs_means_no_genes(self):
        self.assertEqual(_ensembl_gene_ids([]), set())


class ExpressionRowTests(SimpleTestCase):
    def test_maps_bulk_columns_to_the_pilot_shape(self):
        row = _expression_row(
            {
                "Anatomical entity name": "liver",
                "Expression": "present",
                "Call quality": "gold quality",
                "FDR": "0.001",
                "Expression score": "88.5",
            }
        )
        self.assertEqual(row["tissue"], "liver")
        self.assertEqual(row["score"], 88.5)
        self.assertEqual(row["state"], "present")
        self.assertEqual(row["quality"], "gold quality")

    def test_row_without_score_is_dropped(self):
        self.assertIsNone(_expression_row({"Expression score": ""}))


class LoadHumanExpressionBulkTests(TestCase):
    def _make_human_protein(self, accession, ensembl_gene=""):
        biodatabase, _ = Biodatabase.objects.get_or_create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        cross_refs = [{"database": "Bgee", "id": ensembl_gene}] if ensembl_gene else []
        return HumanProtein.objects.create(
            bioentry=bioentry, uniprot_accession=accession, cross_references_raw=cross_refs
        )

    def _write_tsv(self, tmpdir, gz=True):
        path = Path(tmpdir) / ("bgee.tsv.gz" if gz else "bgee.tsv")
        if gz:
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(_BGEE_TSV)
        else:
            path.write_text(_BGEE_TSV, encoding="utf-8")
        return str(path)

    def test_loads_rows_for_the_matching_gene_only(self):
        egfr = self._make_human_protein("P00533", ensembl_gene="ENSG00000146648")
        unmatched = self._make_human_protein("Q00000")
        with tempfile.TemporaryDirectory() as tmpdir:
            call_command("load_human_expression_bulk", bgee_tsv=self._write_tsv(tmpdir))

        egfr.refresh_from_db()
        unmatched.refresh_from_db()
        self.assertEqual([r["tissue"] for r in egfr.expression_json], ["liver", "brain"])
        self.assertEqual(unmatched.expression_json, [])

    def test_dry_run_writes_nothing(self):
        egfr = self._make_human_protein("P00533", ensembl_gene="ENSG00000146648")
        with tempfile.TemporaryDirectory() as tmpdir:
            call_command(
                "load_human_expression_bulk",
                bgee_tsv=self._write_tsv(tmpdir, gz=False),
                dry_run=True,
            )

        egfr.refresh_from_db()
        self.assertEqual(egfr.expression_json, [])

"""Tests for the full-proteome bulk ingest command.

The streaming mechanics (`ijson.items(fh, "results.item")` against both plain
and gzip-wrapped files) were verified this session against a real UniProt
bulk-stream response for P10721/O00116 before this command was written --
these tests check the Django/DB-facing write logic on top of that, using a
small in-memory fixture shaped exactly like that real response.
"""

import gzip
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Biosequence import Biosequence
from bioseq.models.BioentryDbxref import BioentryDbxref

from human_target.models.HumanProtein import HumanProtein
from human_target.services.human_targets import HUMAN_BIODATABASE_NAME

_SAMPLE_ENTRY = {
    "primaryAccession": "P10721",
    "uniProtkbId": "KIT_HUMAN",
    "entryType": "UniProtKB reviewed (Swiss-Prot)",
    "annotationScore": 5.0,
    "entryAudit": {"entryVersion": 267},
    "organism": {"scientificName": "Homo sapiens", "taxonId": 9606, "lineage": []},
    "proteinDescription": {
        "recommendedName": {"fullName": {"value": "Mast/stem cell growth factor receptor Kit"}}
    },
    "genes": [{"geneName": {"value": "KIT"}}],
    "sequence": {"value": "MRGARGAWDFLCVLLLLLRVQTGSS", "length": 25, "molWeight": 2778},
    "comments": [{"commentType": "FUNCTION", "texts": [{"value": "Tyrosine-protein kinase."}]}],
    "features": [],
    "keywords": [],
    "references": [],
    "uniProtKBCrossReferences": [{"database": "GeneID", "id": "3815"}],
}

_SAMPLE_BULK_RESPONSE = {"results": [_SAMPLE_ENTRY]}


class ImportHumanProteomeBulkTests(TestCase):
    def _write_bulk_file(self, tmp_dir, gz=False):
        path = Path(tmp_dir) / ("bulk.json.gz" if gz else "bulk.json")
        payload = json.dumps(_SAMPLE_BULK_RESPONSE).encode("utf-8")
        if gz:
            with gzip.open(path, "wb") as fh:
                fh.write(payload)
        else:
            path.write_bytes(payload)
        return path

    def test_ingests_a_plain_json_bulk_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp, gz=False)
            call_command("import_human_proteome_bulk", str(path))

        human_protein = HumanProtein.objects.get(uniprot_accession="P10721")
        self.assertEqual(human_protein.gene_symbol, "KIT")
        self.assertEqual(human_protein.sequence_length, 25)

    def test_ingests_a_gzipped_bulk_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp, gz=True)
            call_command("import_human_proteome_bulk", str(path))

        self.assertTrue(HumanProtein.objects.filter(uniprot_accession="P10721").exists())

    def test_writes_biosequence_so_fasta_dump_tools_can_read_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp)
            call_command("import_human_proteome_bulk", str(path))

        bioentry = Bioentry.objects.get(
            biodatabase__name=HUMAN_BIODATABASE_NAME, accession="P10721"
        )
        biosequence = Biosequence.objects.get(bioentry=bioentry)
        self.assertEqual(biosequence.seq, "MRGARGAWDFLCVLLLLLRVQTGSS")
        self.assertEqual(biosequence.length, 25)

    def test_writes_unip_sp_dbxref_for_is_direct_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp)
            call_command("import_human_proteome_bulk", str(path))

        bioentry = Bioentry.objects.get(
            biodatabase__name=HUMAN_BIODATABASE_NAME, accession="P10721"
        )
        dbxref = BioentryDbxref.objects.get(bioentry=bioentry)
        self.assertEqual(dbxref.dbxref.dbname, "UnipSp")
        self.assertEqual(dbxref.dbxref.accession, "P10721")

    def test_accession_filter_restricts_ingestion(self):
        bulk_two = {
            "results": [
                _SAMPLE_ENTRY,
                {
                    **_SAMPLE_ENTRY,
                    "primaryAccession": "O00116",
                    "genes": [{"geneName": {"value": "AGPS"}}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bulk.json"
            path.write_text(json.dumps(bulk_two), encoding="utf-8")
            call_command("import_human_proteome_bulk", str(path), accession=["P10721"])

        self.assertTrue(HumanProtein.objects.filter(uniprot_accession="P10721").exists())
        self.assertFalse(HumanProtein.objects.filter(uniprot_accession="O00116").exists())

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp)
            call_command("import_human_proteome_bulk", str(path), dry_run=True)

        self.assertFalse(HumanProtein.objects.filter(uniprot_accession="P10721").exists())
        self.assertFalse(Biodatabase.objects.filter(name=HUMAN_BIODATABASE_NAME).exists())

    def test_rerun_is_idempotent_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_bulk_file(tmp)
            call_command("import_human_proteome_bulk", str(path))
            call_command("import_human_proteome_bulk", str(path))

        self.assertEqual(HumanProtein.objects.filter(uniprot_accession="P10721").count(), 1)
        bioentry = Bioentry.objects.get(
            biodatabase__name=HUMAN_BIODATABASE_NAME, accession="P10721"
        )
        self.assertEqual(Biosequence.objects.filter(bioentry=bioentry).count(), 1)

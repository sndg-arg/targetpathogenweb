"""A re-run of `load_af_model` against a PDB code that already exists must
still ensure *this* bioentry is linked to it -- previously it bailed out via
sys.exit(1) without checking/creating the BioentryStructure link at all,
silently leaving a protein's Structure tab empty if that link was ever
missing (found via the Human Targets re-ingest: structures logged as
"already exists" for a protein whose page showed no Structure tab)."""

import tempfile

from django.core.management import call_command
from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB


class LoadAfModelRelinkTests(TestCase):
    def _make_bioentry(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        return Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )

    def test_relinks_existing_pdb_row_missing_its_bioentry_link(self):
        bioentry = self._make_bioentry("P10721")
        pdb_model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        self.assertFalse(
            BioentryStructure.objects.filter(bioentry=bioentry, pdb=pdb_model).exists()
        )

        with tempfile.NamedTemporaryFile(suffix=".cif") as f:
            with self.assertRaises(SystemExit):
                call_command("load_af_model", "AF_P10721", f.name, "P10721", experiment="AF")

        self.assertTrue(BioentryStructure.objects.filter(bioentry=bioentry, pdb=pdb_model).exists())

    def test_does_not_duplicate_an_already_existing_link(self):
        bioentry = self._make_bioentry("P10721")
        pdb_model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        BioentryStructure.objects.create(bioentry=bioentry, pdb=pdb_model)

        with tempfile.NamedTemporaryFile(suffix=".cif") as f:
            with self.assertRaises(SystemExit):
                call_command("load_af_model", "AF_P10721", f.name, "P10721", experiment="AF")

        self.assertEqual(
            BioentryStructure.objects.filter(bioentry=bioentry, pdb=pdb_model).count(), 1
        )

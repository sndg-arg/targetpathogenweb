"""A re-run of `load_af_model` against a PDB code that already exists must
still ensure *this* bioentry is linked to it -- previously it bailed out via
sys.exit(1) without checking/creating the BioentryStructure link at all,
silently leaving a protein's Structure tab empty if that link was ever
missing (found via the Human Targets re-ingest: structures logged as
"already exists" for a protein whose page showed no Structure tab)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Atom
from tpweb.management.commands.load_af_model import Command


class LoadAfModelRelinkTests(TestCase):
    @staticmethod
    def _populate(pdb_model, path=None):
        residue = Residue.objects.create(pdb=pdb_model, chain="A", resname="ALA", resid=1, type="R")
        Atom.objects.create(
            residue=residue,
            serial=1,
            name="CA",
            altLoc=" ",
            x=0,
            y=0,
            z=0,
            occupancy=1,
            bfactor=20,
            element="C",
        )

    def _make_bioentry(self, accession):
        biodatabase = Biodatabase.objects.create(name="human_curated_prots")
        return Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )

    def test_relinks_existing_pdb_row_missing_its_bioentry_link(self):
        bioentry = self._make_bioentry("P10721")
        pdb_model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        self._populate(pdb_model)
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
        self._populate(pdb_model)
        BioentryStructure.objects.create(bioentry=bioentry, pdb=pdb_model)

        with tempfile.NamedTemporaryFile(suffix=".cif") as f:
            with self.assertRaises(SystemExit):
                call_command("load_af_model", "AF_P10721", f.name, "P10721", experiment="AF")

        self.assertEqual(
            BioentryStructure.objects.filter(bioentry=bioentry, pdb=pdb_model).count(), 1
        )

    def test_repair_preserves_existing_id_and_links(self):
        bioentry = self._make_bioentry("P10721")
        model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        link = BioentryStructure.objects.create(bioentry=bioentry, pdb=model)
        with (
            tempfile.TemporaryDirectory() as datadir,
            patch.object(Command, "load_pdb_file", side_effect=self._populate),
        ):
            source = Path(datadir) / "source.cif"
            source.write_text("")
            call_command(
                "load_af_model",
                model.code,
                str(source),
                bioentry.accession,
                experiment="AF",
                datadir=datadir,
            )
        link.refresh_from_db()
        self.assertEqual(link.pdb_id, model.pk)
        self.assertEqual(Atom.objects.filter(residue__pdb=model).count(), 1)
        self.assertEqual(BioentryStructure.objects.filter(pdb=model).count(), 1)

    def test_empty_reparse_fails_without_claiming_success(self):
        bioentry = self._make_bioentry("P10721")
        model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")
        link = BioentryStructure.objects.create(bioentry=bioentry, pdb=model)
        residue = Residue.objects.create(pdb=model, chain="A", resname="ALA", resid=1, type="R")
        with (
            tempfile.NamedTemporaryFile(suffix=".cif") as source,
            tempfile.TemporaryDirectory() as datadir,
            patch.object(Command, "load_pdb_file"),
            self.assertRaisesMessage(CommandError, "contains no atoms"),
        ):
            call_command(
                "load_af_model",
                model.code,
                source.name,
                bioentry.accession,
                experiment="AF",
                datadir=datadir,
            )
        self.assertTrue(Residue.objects.filter(pk=residue.pk).exists())
        self.assertTrue(BioentryStructure.objects.filter(pk=link.pk).exists())

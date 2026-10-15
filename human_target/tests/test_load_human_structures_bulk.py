import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_structures_bulk import (
    _guess_experimental_method,
    _index_alphafold_dir,
    _pdb_ids_from_cross_references,
)
from human_target.models.HumanProtein import HumanProtein
from tpweb.models.BioentryStructure import ExperimentalStructureXref
from tpweb.models.pdb import PDB

_FAKE_CIF_WITH_METHOD = "_exptl.method   'X-RAY DIFFRACTION'\n"


class IndexAlphafoldDirTests(SimpleTestCase):
    def test_indexes_files_by_accession_ignoring_version_and_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "AF-P10721-F1-model_v4.cif").write_text("x")
            (tmp_path / "AF-O00116-F1-model_v3.cif.gz").write_text("x")
            (tmp_path / "README.txt").write_text("x")

            index = _index_alphafold_dir(tmp_path)

        self.assertEqual(set(index), {"P10721", "O00116"})
        self.assertTrue(index["P10721"].name.endswith(".cif"))
        self.assertTrue(index["O00116"].name.endswith(".cif.gz"))


class PdbIdsFromCrossReferencesTests(SimpleTestCase):
    def test_extracts_pdb_xrefs_only_uppercased(self):
        xrefs = [
            {"database": "RefSeq", "id": "NP_000001"},
            {"database": "PDB", "id": "1abc"},
        ]
        self.assertEqual(_pdb_ids_from_cross_references(xrefs), ["1ABC"])

    def test_no_pdb_returns_empty_list(self):
        self.assertEqual(_pdb_ids_from_cross_references([{"database": "RefSeq", "id": "x"}]), [])
        self.assertEqual(_pdb_ids_from_cross_references(None), [])


class GuessExperimentalMethodTests(SimpleTestCase):
    def test_extracts_method_from_cif_text(self):
        self.assertEqual(_guess_experimental_method(_FAKE_CIF_WITH_METHOD), "X-RAY DIFFRACTION")

    def test_missing_method_returns_empty_string(self):
        self.assertEqual(_guess_experimental_method("no method here"), "")


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class LoadHumanStructuresBulkTests(TestCase):
    def _make_human_protein(self, accession, pdb_ids=()):
        biodatabase, _ = Biodatabase.objects.get_or_create(name="human_curated_prots")
        bioentry = Bioentry.objects.create(
            biodatabase=biodatabase, name=accession, accession=accession, identifier=accession
        )
        cross_refs = [{"database": "PDB", "id": pdb_id} for pdb_id in pdb_ids]
        return HumanProtein.objects.create(
            bioentry=bioentry,
            uniprot_accession=accession,
            cross_references_raw=cross_refs,
        )

    def test_alphafold_relinks_an_existing_pdb_row_found_in_the_index(self):
        self._make_human_protein("P10721")
        bioentry = Bioentry.objects.get(accession="P10721")
        PDB.objects.create(code="AF_P10721", experiment="AF", text="")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "AF-P10721-F1-model_v4.cif").write_text("x")
            call_command(
                "load_human_structures_bulk",
                alphafold_dir=str(tmp_path),
                accession=["P10721"],
                skip_experimental=True,
            )

        self.assertTrue(bioentry.structures.filter(pdb__code="AF_P10721").exists())

    def test_alphafold_missing_file_is_skipped_without_error(self):
        self._make_human_protein("P10721")

        with tempfile.TemporaryDirectory() as tmp:
            call_command(
                "load_human_structures_bulk",
                alphafold_dir=tmp,
                accession=["P10721"],
                skip_experimental=True,
            )

        self.assertFalse(PDB.objects.filter(code="AF_P10721").exists())

    @patch(
        "human_target.management.commands.load_human_structures_bulk.requests.get",
        return_value=_FakeResponse(_FAKE_CIF_WITH_METHOD),
    )
    def test_experimental_downloads_once_and_links_every_sharing_protein(self, mock_get):
        self._make_human_protein("P10721", pdb_ids=["1ABC"])
        self._make_human_protein("P10722", pdb_ids=["1ABC"])

        call_command(
            "load_human_structures_bulk",
            skip_alphafold=True,
            accession=["P10721", "P10722"],
        )

        mock_get.assert_called_once()
        self.assertEqual(ExperimentalStructureXref.objects.filter(pdb_id="1ABC").count(), 2)
        xref = ExperimentalStructureXref.objects.get(pdb_id="1ABC", bioentry__accession="P10721")
        self.assertEqual(xref.method, "X-RAY DIFFRACTION")

    @patch("human_target.management.commands.load_human_structures_bulk.requests.get")
    def test_experimental_skips_download_when_pdb_already_loaded(self, mock_get):
        # Resuming an interrupted run shouldn't re-download every entry
        # already loaded by the previous attempt.
        self._make_human_protein("P10721", pdb_ids=["1ABC"])
        self._make_human_protein("P10722", pdb_ids=["1ABC"])
        PDB.objects.create(code="1ABC", experiment="EX", text="")
        ExperimentalStructureXref.objects.create(
            bioentry=Bioentry.objects.get(accession="P10721"),
            pdb_id="1ABC",
            method="SOLUTION NMR",
        )

        call_command(
            "load_human_structures_bulk",
            skip_alphafold=True,
            accession=["P10721", "P10722"],
        )

        mock_get.assert_not_called()
        xref = ExperimentalStructureXref.objects.get(pdb_id="1ABC", bioentry__accession="P10722")
        self.assertEqual(xref.method, "SOLUTION NMR")

    @patch(
        "human_target.management.commands.load_human_structures_bulk.requests.get",
        return_value=_FakeResponse(_FAKE_CIF_WITH_METHOD),
    )
    def test_experimental_processes_distinct_entries_concurrently_and_aggregates_correctly(
        self, mock_get
    ):
        self._make_human_protein("P10721", pdb_ids=["1ABC"])
        self._make_human_protein("P10722", pdb_ids=["2XYZ"])
        self._make_human_protein("P10723", pdb_ids=["3QRS"])

        call_command(
            "load_human_structures_bulk",
            skip_alphafold=True,
            accession=["P10721", "P10722", "P10723"],
            workers=3,
        )

        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(ExperimentalStructureXref.objects.count(), 3)
        self.assertEqual(PDB.objects.filter(experiment="EX").count(), 3)

    @patch("human_target.management.commands.load_human_structures_bulk.requests.get")
    def test_experimental_with_no_pdb_xrefs_skips_without_calling_requests(self, mock_get):
        self._make_human_protein("P10721")

        call_command(
            "load_human_structures_bulk",
            skip_alphafold=True,
            accession=["P10721"],
        )

        mock_get.assert_not_called()

    def test_missing_alphafold_dir_without_skip_raises(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("load_human_structures_bulk", accession=["P10721"])

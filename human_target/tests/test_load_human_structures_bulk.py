import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from human_target.management.commands.load_human_structures_bulk import (
    Command,
    _guess_experimental_method,
    _index_alphafill_dir,
    _index_alphafold_dir,
    _pdb_ids_from_cross_references,
)
from human_target.models.HumanProtein import HumanProtein
from tpweb.models.BioentryStructure import ExperimentalStructureXref
from tpweb.models.pdb import PDB, Atom

_FAKE_CIF_WITH_METHOD = """data_test
_exptl.method   'X-RAY DIFFRACTION'
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 0.0 0.0 0.0 1.0 20.0 1 A 1
#
"""


class AlphaFillParallelTests(SimpleTestCase):
    def test_workers_get_disjoint_accessions_and_effective_test_database(self):
        module = "human_target.management.commands.load_human_structures_bulk"
        jobs = [(f"AFILL_T{i}", f"/raw/{i}.cif", f"T{i}") for i in range(5)]
        captured = []

        def run(command, **kwargs):
            path = command[command.index("--accession-file") + 1]
            captured.append((command, Path(path).read_text().splitlines(), kwargs["env"]))
            return SimpleNamespace(returncode=0)

        with (
            patch(f"{module}.connections") as db,
            patch(f"{module}.subprocess.run", side_effect=run),
        ):
            db.__getitem__.return_value.settings_dict = {"NAME": "test_alpha", "HOST": "db"}
            Command()._load_alphafill_parallel(
                jobs, {"alphafill_dir": "/raw", "datadir": "/data", "overwrite": False}, 2
            )
        self.assertEqual(len(captured), 2)
        partitions = [set(rows) for _, rows, _ in captured]
        self.assertFalse(partitions[0] & partitions[1])
        self.assertEqual(partitions[0] | partitions[1], {f"T{i}" for i in range(5)})
        for command, _, env in captured:
            self.assertEqual(env["DJANGO_DATABASE_NAME"], "test_alpha")
            self.assertNotIn("--alphafill-workers", command)
            self.assertNotIn("--overwrite", command)

    def test_failed_worker_does_not_report_success(self):
        module = "human_target.management.commands.load_human_structures_bulk"
        with patch(f"{module}.connections") as db, patch(f"{module}.subprocess.run") as run:
            db.__getitem__.return_value.settings_dict = {"NAME": "test_alpha"}
            run.return_value.returncode = 1
            with self.assertRaisesMessage(CommandError, "completed structures are preserved"):
                Command()._load_alphafill_parallel(
                    [("AFILL_T1", "/raw/1.cif", "T1")],
                    {"alphafill_dir": "/raw", "datadir": "/data", "overwrite": False},
                    2,
                )


class AlphaFillBulkTests(SimpleTestCase):
    def test_index_selects_latest_canonical_version_in_flat_and_sharded_bank(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "P0").mkdir()
            for name in (
                "AF-P07203-F1-filled_v4.cif.gz",
                "AF-P07203-F1-filled_v10.cif.gz",
                "AF-P07203-F2-filled_v11.cif.gz",
                "AF-P07203-F1-model_v12.cif.gz",
                "AF-P07203-F1-filled_v10.cif.json",
            ):
                (root / "P0" / name).touch()
            (root / "AF-O00116-F1-filled_v4.cif").touch()
            index = _index_alphafill_dir(root)
            self.assertEqual(set(index), {"P07203", "O00116"})
            self.assertEqual(index["P07203"].name, "AF-P07203-F1-filled_v10.cif.gz")

    def test_resume_skips_completed_but_retries_failed_and_missing_links(self):
        module = "human_target.management.commands.load_human_structures_bulk"
        rows = [("P1", [], 1), ("P2", [], 2), ("P3", [], 3), ("P4", [], 4)]
        with (
            patch(f"{module}._index_alphafill_dir", return_value={"P1": "a", "P2": "b", "P3": "c"}),
            patch(f"{module}.BioentryStructure.objects.filter") as links,
            patch.object(Command, "_call_load_af_model", side_effect=[False, True]) as load,
        ):
            links.return_value.values_list.return_value = [(1, "AFILL_P1")]
            with self.assertRaisesMessage(CommandError, "1 structures failed"):
                Command()._load_alphafill(rows, {"alphafill_dir": "bank", "overwrite": False})
            self.assertEqual([call.args[2] for call in load.call_args_list], ["P2", "P3"])
            self.assertTrue(all(call.args[3] == "AFILL" for call in load.call_args_list))

    def test_empty_bank_fails_instead_of_reporting_success(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesMessage(CommandError, "No canonical AlphaFill"),
        ):
            Command()._load_alphafill([("P1", [], 1)], {"alphafill_dir": tmp})


class ExperimentalResumeTests(SimpleTestCase):
    def test_parse_failure_counts_entry_as_failed_without_writing_xref(self):
        module = "human_target.management.commands.load_human_structures_bulk"
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(f"{module}.PDB.objects.filter") as pdb,
            patch(f"{module}.requests.get", return_value=_FakeResponse(_FAKE_CIF_WITH_METHOD)),
            patch.object(Command, "_call_load_af_model", return_value=False),
            patch(f"{module}.ExperimentalStructureXref.objects.update_or_create") as write,
        ):
            pdb.return_value.exists.return_value = False
            result = Command()._process_one_experimental_entry(
                "3JPN", ["P1"], {"P1": 1}, {"overwrite": False}, tmp
            )
            self.assertEqual(result, (0, 1))
            write.assert_not_called()

    def test_resume_requires_both_xref_and_structure_link(self):
        rows = [
            ("P1", [{"database": "PDB", "id": "1ABC"}], 1),
            ("P2", [{"database": "PDB", "id": "1ABC"}], 2),
            ("P3", [{"database": "PDB", "id": "2ABC"}], 3),
        ]
        module = "human_target.management.commands.load_human_structures_bulk"
        for overwrite in (False, True):
            with (
                self.subTest(overwrite=overwrite),
                patch(f"{module}.ExperimentalStructureXref.objects.filter") as xrefs,
                patch(f"{module}.BioentryStructure.objects.filter") as links,
                patch.object(
                    Command, "_process_one_experimental_entry", return_value=(1, 0)
                ) as process,
            ):
                xrefs.return_value.values_list.return_value.iterator.return_value = [
                    (1, "1ABC"),
                    (2, "1ABC"),
                ]
                links.return_value.values_list.return_value.iterator.return_value = [
                    (1, "1ABC"),
                    (3, "2ABC"),
                ]
                Command()._load_experimental(rows, {"overwrite": overwrite, "workers": 1})
                pending = {call.args[0]: call.args[1] for call in process.call_args_list}
                self.assertEqual(
                    pending, {"1ABC": ["P1", "P2"] if overwrite else ["P2"], "2ABC": ["P3"]}
                )

    def test_completed_run_submits_no_work(self):
        module = "human_target.management.commands.load_human_structures_bulk"
        with (
            patch(f"{module}.ExperimentalStructureXref.objects.filter") as xrefs,
            patch(f"{module}.BioentryStructure.objects.filter") as links,
            patch(f"{module}.ThreadPoolExecutor") as pool,
        ):
            for query in (xrefs, links):
                query.return_value.values_list.return_value.iterator.return_value = [(1, "1ABC")]
            Command()._load_experimental(
                [("P1", [{"database": "PDB", "id": "1ABC"}], 1)],
                {"overwrite": False, "workers": 1},
            )
            pool.assert_not_called()


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


class LoadHumanStructuresBulkTests(TransactionTestCase):
    # Experimental entries load in worker threads, each with its own DB
    # connection: they only see committed rows, which TestCase never commits.
    def setUp(self):
        super().setUp()
        datadir = tempfile.TemporaryDirectory()
        self.addCleanup(datadir.cleanup)
        self.datadir = datadir.name

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

    def test_alphafill_two_processes_load_disjoint_models(self):
        accessions = ["T" + uuid4().hex[:9].upper() for _ in range(2)]
        for accession in accessions:
            self._make_human_protein(accession)
        with tempfile.TemporaryDirectory() as tmp:
            for accession in accessions:
                Path(tmp, f"AF-{accession}-F1-filled_v4.cif").write_text(_FAKE_CIF_WITH_METHOD)
            call_command(
                "load_human_structures_bulk",
                datadir=self.datadir,
                skip_alphafold=True,
                skip_experimental=True,
                alphafill_dir=tmp,
                accession=accessions,
                alphafill_workers=2,
            )
        self.assertEqual(
            Atom.objects.filter(residue__pdb__code__in=[f"AFILL_{a}" for a in accessions]).count(),
            2,
        )

    def test_alphafold_repairs_empty_existing_row_without_changing_its_id(self):
        self._make_human_protein("P10721")
        bioentry = Bioentry.objects.get(accession="P10721")
        model = PDB.objects.create(code="AF_P10721", experiment="AF", text="")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "AF-P10721-F1-model_v4.cif").write_text(_FAKE_CIF_WITH_METHOD)
            call_command(
                "load_human_structures_bulk",
                datadir=self.datadir,
                alphafold_dir=str(tmp_path),
                accession=["P10721"],
                skip_experimental=True,
            )

        self.assertTrue(bioentry.structures.filter(pdb__code="AF_P10721").exists())
        self.assertEqual(PDB.objects.get(code="AF_P10721").pk, model.pk)
        self.assertEqual(Atom.objects.filter(residue__pdb=model).count(), 1)

    def test_alphafill_retries_linked_but_empty_row(self):
        protein = self._make_human_protein("O00116")
        model = PDB.objects.create(code="AFILL_O00116", experiment="AFILL", text="")
        from tpweb.models.BioentryStructure import BioentryStructure

        BioentryStructure.objects.create(bioentry=protein.bioentry, pdb=model)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "AF-O00116-F1-filled_v4.cif").write_text(_FAKE_CIF_WITH_METHOD)
            call_command(
                "load_human_structures_bulk",
                datadir=self.datadir,
                skip_alphafold=True,
                skip_experimental=True,
                alphafill_dir=tmp,
                accession=["O00116"],
            )
        self.assertEqual(PDB.objects.get(code="AFILL_O00116").pk, model.pk)
        self.assertEqual(Atom.objects.filter(residue__pdb=model).count(), 1)
        self.assertEqual(BioentryStructure.objects.filter(pdb=model).count(), 1)

    def test_alphafold_missing_file_is_skipped_without_error(self):
        self._make_human_protein("P10721")

        with tempfile.TemporaryDirectory() as tmp:
            call_command(
                "load_human_structures_bulk",
                datadir=self.datadir,
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
            datadir=self.datadir,
            skip_alphafold=True,
            accession=["P10721", "P10722"],
        )

        mock_get.assert_called_once()
        self.assertEqual(ExperimentalStructureXref.objects.filter(pdb_id="1ABC").count(), 2)
        xref = ExperimentalStructureXref.objects.get(pdb_id="1ABC", bioentry__accession="P10721")
        self.assertEqual(xref.method, "X-RAY DIFFRACTION")
        for accession in ("P10721", "P10722"):
            self.assertTrue(
                Bioentry.objects.get(accession=accession)
                .structures.filter(pdb__code="1ABC", pdb__experiment="EX")
                .exists()
            )

    @patch("human_target.management.commands.load_human_structures_bulk.requests.get")
    def test_experimental_skips_download_when_pdb_already_loaded(self, mock_get):
        # Resuming an interrupted run shouldn't re-download every entry
        # already loaded by the previous attempt.
        self._make_human_protein("P10721", pdb_ids=["1ABC"])
        self._make_human_protein("P10722", pdb_ids=["1ABC"])
        # Reuse requires actual geometry; an empty legacy row must be fetched again.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "1ABC.cif")
            path.write_text(_FAKE_CIF_WITH_METHOD)
            call_command(
                "load_af_model",
                "1ABC",
                str(path),
                "P10721",
                experiment="EX",
                datadir=self.datadir,
            )
        ExperimentalStructureXref.objects.create(
            bioentry=Bioentry.objects.get(accession="P10721"),
            pdb_id="1ABC",
            method="SOLUTION NMR",
        )

        call_command(
            "load_human_structures_bulk",
            datadir=self.datadir,
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
            datadir=self.datadir,
            skip_alphafold=True,
            accession=["P10721", "P10722", "P10723"],
            workers=3,
        )

        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(ExperimentalStructureXref.objects.count(), 3)
        self.assertEqual(PDB.objects.filter(experiment="EX").count(), 3)
        for accession, code in (("P10721", "1ABC"), ("P10722", "2XYZ"), ("P10723", "3QRS")):
            self.assertTrue(
                Bioentry.objects.get(accession=accession)
                .structures.filter(pdb__code=code, pdb__experiment="EX")
                .exists()
            )

    @patch("human_target.management.commands.load_human_structures_bulk.requests.get")
    def test_experimental_with_no_pdb_xrefs_skips_without_calling_requests(self, mock_get):
        self._make_human_protein("P10721")

        call_command(
            "load_human_structures_bulk",
            datadir=self.datadir,
            skip_alphafold=True,
            accession=["P10721"],
        )

        mock_get.assert_not_called()

    def test_missing_alphafold_dir_without_skip_raises(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("load_human_structures_bulk", accession=["P10721"])

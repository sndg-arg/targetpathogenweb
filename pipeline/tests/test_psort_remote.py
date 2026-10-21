"""PSORT correctness, checkpointing and remote lifecycle without cluster access."""

import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psort_remote as remote  # noqa: E402
import psort_worker as worker  # noqa: E402


class PredictionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw.txt"
        self.fasta = self.root / "input.faa"
        self.fasta.write_text(">A description\nMUA\n>B\nMXX\n", encoding="utf-8")

    def parse(self, text, expected=None):
        self.raw.write_text(text, encoding="utf-8")
        return worker.read_predictions(self.raw, expected or {"A", "B"})

    def test_valid_predictions_include_unknown_and_preserve_sequence(self):
        rows = self.parse("SeqID\tLocalization\tScore\nA\tUnknown\t0\nB\tCytoplasmic\t9\n")
        self.assertEqual(rows, {"A": "Unknown", "B": "Cytoplasmic"})
        self.assertEqual(worker.read_fasta(self.fasta)[0], ("A", "MUA"))

    def test_error_header_empty_duplicate_missing_extra_and_invalid_rows_rejected(self):
        cases = [
            "Fatal error: SCLBLAST_NO_RESULT: A\n",
            "SeqID\tLocalization\n",
            "SeqID\tLocalization\nA\tUnknown\nA\tUnknown\n",
            "SeqID\tLocalization\nA\tUnknown\n",
            "SeqID\tLocalization\nA\tUnknown\nB\tUnknown\nC\tUnknown\n",
            "SeqID\tLocalization\nA\tERROR\nB\tUnknown\n",
            "SeqID\tLocalization\n\tUnknown\nB\tUnknown\n",
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_duplicate_or_empty_fasta_rejected(self):
        for text in (">A\nMM\n>A\nMX\n", ">A\n", "", ">\nMM\n"):
            self.fasta.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ValueError):
                worker.read_fasta(self.fasta)

    def test_compressed_fasta_can_validate_a_resumed_stage21(self):
        with gzip.open(str(self.fasta) + ".gz", "wt", encoding="utf-8") as handle:
            handle.write(self.fasta.read_text(encoding="utf-8"))
        self.fasta.unlink()
        self.assertEqual(worker.read_fasta(self.fasta), [("A", "MUA"), ("B", "MXX")])

    def test_diagnostic_keeps_failure_and_reports_query_id(self):
        source = "my $bres = $brep->next_result();\nwhile(my $hit = $bres->next_hit()) {}"
        result = worker.instrument_module(source)
        self.assertIn("SCLBLAST_NO_RESULT", result)
        self.assertIn("$seq->display_id", result)
        self.assertIn("die", result)
        with self.assertRaises(ValueError):
            worker.instrument_module("unknown version")

    def test_atomic_normalized_output_round_trip(self):
        records = worker.read_fasta(self.fasta)
        worker.write_predictions(self.raw, {"A": "Unknown", "B": "Periplasmic"}, records)
        self.assertEqual(
            worker.validate_psort_file(self.raw, self.fasta), {"A": "Unknown", "B": "Periplasmic"}
        )

    def test_valid_batch_reused_without_starting_psort(self):
        worker.write_predictions(self.root / "batch-00000.tsv", {"A": "Unknown"}, [("A", "MU")])
        with patch.object(worker.subprocess, "run") as run:
            result = worker._run_batch(
                0, [("A", "MU")], self.root, "apptainer", "image", "n", "module", 30
            )
        run.assert_not_called()
        self.assertEqual(result, {"A": "Unknown"})

    def test_zero_exit_with_fatal_raw_output_does_not_create_checkpoint(self):
        def fake_run(command, **kwargs):
            batch = Path(command[command.index("--bind") + 1].removesuffix(":/tmp"))
            (batch / "results" / "date_psortb_gramneg.txt").write_text(
                "Fatal error: SCLBLAST_NO_RESULT: A\n", encoding="utf-8"
            )
            return SimpleNamespace(returncode=0)

        with patch.object(worker.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "SCLBLAST_NO_RESULT"):
                worker._run_batch(
                    0, [("A", "MU")], self.root, "apptainer", "image", "n", "module", 30
                )
        self.assertFalse((self.root / "batch-00000.tsv").exists())
        self.assertEqual(len(list(self.root.glob("batch-*/input.faa"))), 1)

    def test_successful_batch_is_validated_and_checkpointed(self):
        def fake_run(command, **kwargs):
            self.assertIn("--containall", command)
            batch = Path(command[command.index("--bind") + 1].removesuffix(":/tmp"))
            (batch / "results" / "date_psortb_gramneg.txt").write_text(
                "SeqID\tLocalization\tScore\nA\tUnknown\t0\n", encoding="utf-8"
            )
            return SimpleNamespace(returncode=0)

        with patch.object(worker.subprocess, "run", side_effect=fake_run):
            worker._run_batch(0, [("A", "MU")], self.root, "apptainer", "image", "n", "module", 30)
        self.assertTrue((self.root / "batch-00000.tsv").exists())

    def test_parallel_batches_resume_and_image_change_invalidates_cache(self):
        image = self.root / "psort.sif"
        image.write_bytes(b"version-one")
        output = self.root / "psort.tsv"

        def fake_run(command, **kwargs):
            batch = Path(command[command.index("--bind") + 1].removesuffix(":/tmp"))
            records = worker.read_fasta(batch / "input.faa")
            raw = "SeqID\tLocalization\n" + "".join(f"{name}\tUnknown\n" for name, _ in records)
            (batch / "results" / "date_psortb_gramneg.txt").write_text(raw, encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with (
            patch.object(worker.subprocess, "run", side_effect=fake_run) as run,
            patch.object(
                worker.subprocess, "check_output", return_value="my $bres = $brep->next_result();"
            ),
        ):
            for _ in range(2):
                worker.run_batches(
                    self.fasta,
                    output,
                    self.root / "cache",
                    "apptainer",
                    str(image),
                    "n",
                    workers=2,
                    batch_size=1,
                )
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                worker.validate_psort_file(output, self.fasta), {"A": "Unknown", "B": "Unknown"}
            )
            image.write_bytes(b"version-two")
            worker.run_batches(
                self.fasta,
                output,
                self.root / "cache",
                "apptainer",
                str(image),
                "n",
                workers=2,
                batch_size=1,
            )
            self.assertEqual(run.call_count, 4)


def config():
    return SimpleNamespace(
        ssh_rootfolder="/home/test",
        ssh_host="cluster",
        ssh_port=22,
        ssh_connect_timeout=10,
        cpus_per_task=4,
        partition="cpu",
        time_limit="04:00:00",
        mem="16G",
        exclude="",
        wait_seconds=60,
        poll_seconds=1,
    )


class RemoteTests(unittest.TestCase):
    def test_script_uses_compute_resources_and_setup_before_nounset(self):
        with patch.dict(os.environ, {"TPW_PSORT_REMOTE_SETUP": "conda activate tools"}, clear=True):
            script = remote._build_script(config(), "/home/test/job", "n")
        self.assertIn("#SBATCH --cpus-per-task=4", script)
        self.assertIn("--workers 4", script)
        self.assertIn("--gram n", script)
        self.assertIn("setup_psort.sh", script)
        self.assertLess(script.index("conda activate"), script.index("set -u"))

    def test_completed_without_done_is_failure(self):
        adapter = SimpleNamespace(
            _exec_remote=MagicMock(side_effect=[(0, "42|COMPLETED|0:0", ""), (1, "", "")])
        )
        with self.assertRaisesRegex(RuntimeError, "without validated output"):
            remote._wait_for_job(None, adapter, config(), "42", "/job")

    def test_failed_slurm_job_includes_diagnostic(self):
        adapter = SimpleNamespace(
            REMOTE_FAILURE_PREFIXES=("FAILED",),
            _exec_remote=MagicMock(
                side_effect=[(0, "42|FAILED|1:0", ""), (0, "SCLBLAST_NO_RESULT: A", "")]
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "SCLBLAST_NO_RESULT: A"):
            remote._wait_for_job(None, adapter, config(), "42", "/job")

    def run_stage(self, content, wait_error=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "G.faa").write_text(">A\nMU\n", encoding="utf-8")
            (root / "psort.tsv").write_text("previous valid result", encoding="utf-8")
            scp = MagicMock()
            scp.get.side_effect = lambda source, target: Path(target).write_text(
                content, encoding="utf-8"
            )
            adapter = SimpleNamespace(
                _build_config=MagicMock(return_value=config()),
                _assert_ssh_reachable=MagicMock(),
                _open_remote_session=MagicMock(return_value=(MagicMock(), scp, MagicMock())),
                _close_remote_session=MagicMock(),
                _exec_remote=MagicMock(side_effect=[(0, "", ""), (0, "42", ""), (0, "", "")]),
            )
            with (
                patch.dict(sys.modules, {"slurm_remote_command": adapter}),
                patch.dict(os.environ, {}, clear=True),
                patch.object(remote, "_wait_for_job", side_effect=wait_error),
            ):
                if wait_error or "Fatal" in content:
                    with self.assertRaises((RuntimeError, ValueError)):
                        remote.run_remote_psort(None, folder, "G", "n")
                    self.assertEqual((root / "psort.tsv").read_text(), "previous valid result")
                else:
                    remote.run_remote_psort(None, folder, "G", "n")
                    self.assertEqual((root / "psort.tsv").read_text(), content)
            adapter._close_remote_session.assert_called_once()
            commands = [call.args[1] for call in adapter._exec_remote.call_args_list]
            self.assertEqual(any(command == "scancel 42" for command in commands), bool(wait_error))

    def test_valid_download_published(self):
        self.run_stage("gene\tLocalization\nA\tUnknown\n")

    def test_invalid_download_preserves_previous_result(self):
        self.run_stage("Fatal error\n")

    def test_wait_failure_cancels_job_and_preserves_previous_result(self):
        self.run_stage("", RuntimeError("remote failure"))


if __name__ == "__main__":
    unittest.main()

"""Cover the orchestration primitives every one of the 24 stages funnels
through: _run_stage / _run_python_stage (event bookkeeping + failure
handling) and the heavy-stage guard rail. Zero coverage before this file,
despite being the part of the app most likely to silently drop a failed
stage as a success (or vice versa) if the event bookkeeping regresses.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import run_pipeline_direct as rpd  # noqa: E402


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RunStageTests(unittest.TestCase):
    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.subprocess.run")
    def test_successful_command_records_submitted_then_completed(self, subprocess_run, record_stage):
        subprocess_run.return_value = FakeCompletedProcess(returncode=0, stdout="ok")

        result = rpd._run_stage(3, "load_gbk", "echo hi")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            [call.kwargs.get("status") for call in record_stage.call_args_list],
            ["submitted", "completed"],
        )
        # the actual command reaches bash unchanged
        ran_command = subprocess_run.call_args.args[0]
        self.assertEqual(ran_command, ["bash", "-c", "echo hi"])

    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.subprocess.run")
    def test_nonzero_returncode_records_failed_and_raises(self, subprocess_run, record_stage):
        subprocess_run.return_value = FakeCompletedProcess(returncode=1, stdout="", stderr="boom")

        with self.assertRaises(RuntimeError) as ctx:
            rpd._run_stage(11, "load_interpro", "false")

        self.assertIn("load_interpro failed (rc=1)", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))
        statuses = [call.kwargs.get("status") for call in record_stage.call_args_list]
        self.assertEqual(statuses, ["submitted", "failed"])

    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.subprocess.run")
    def test_failure_message_falls_back_to_stdout_when_stderr_empty(self, subprocess_run, record_stage):
        subprocess_run.return_value = FakeCompletedProcess(returncode=2, stdout="stdout details", stderr="")

        with self.assertRaises(RuntimeError):
            rpd._run_stage(4, "fasttarget", "false")

        failed_call = record_stage.call_args_list[-1]
        self.assertEqual(failed_call.kwargs["status"], "failed")
        self.assertIn("stdout details", failed_call.kwargs["message"])


class RunPythonStageTests(unittest.TestCase):
    @patch("run_pipeline_direct._record_pipeline_stage")
    def test_successful_callable_records_submitted_then_completed_and_returns_value(self, record_stage):
        result = rpd._run_python_stage(15, "alphafold", lambda x: x + 1, 41)

        self.assertEqual(result, 42)
        self.assertEqual(
            [call.kwargs.get("status") for call in record_stage.call_args_list],
            ["submitted", "completed"],
        )

    @patch("run_pipeline_direct._record_pipeline_stage")
    def test_raising_callable_records_failed_and_propagates(self, record_stage):
        def boom():
            raise ValueError("no GPU available")

        with self.assertRaises(ValueError):
            rpd._run_python_stage(16, "colabfold", boom)

        failed_call = record_stage.call_args_list[-1]
        self.assertEqual(failed_call.kwargs["status"], "failed")
        self.assertIn("no GPU available", failed_call.kwargs["message"])


class HeavyStageGuardTests(unittest.TestCase):
    def test_allows_non_heavy_stage_regardless_of_flag(self):
        rpd._assert_heavy_stage_allowed(3, "load_gbk", allow_local_heavy=False)  # should not raise

    def test_allows_heavy_stage_when_flag_set(self):
        rpd._assert_heavy_stage_allowed(16, "colabfold", allow_local_heavy=True)  # should not raise

    def test_blocks_heavy_stage_without_flag(self):
        with self.assertRaises(RuntimeError) as ctx:
            rpd._assert_heavy_stage_allowed(10, "interproscan", allow_local_heavy=False)
        self.assertIn("stage 10", str(ctx.exception))
        self.assertIn("InterProScan", str(ctx.exception))
        self.assertIn("--allow-local-heavy", str(ctx.exception))


class ComputeFolderPathTests(unittest.TestCase):
    def test_splits_genome_accession_into_middle_bucket_directory(self):
        # Mirrors the on-disk layout documented in CLAUDE.md's genome reset
        # recipe -- get this math wrong and stages read/write the wrong folder.
        # "NZ_AP023069.1" is 13 chars; floor(13/2-1):floor(13/2+2) == [5:8] == "023".
        folder_path = rpd._compute_folder_path("/app/tp", "NZ_AP023069.1")
        self.assertEqual(folder_path, "/app/tp/data/023/NZ_AP023069.1")


if __name__ == "__main__":
    unittest.main()

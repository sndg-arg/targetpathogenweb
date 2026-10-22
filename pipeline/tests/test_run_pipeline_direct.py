"""Cover the orchestration primitives every one of the 24 stages funnels
through: _run_stage / _run_python_stage (event bookkeeping + failure
handling) and the heavy-stage guard rail. Zero coverage before this file,
despite being the part of the app most likely to silently drop a failed
stage as a success (or vice versa) if the event bookkeeping regresses.
"""

import configparser
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_successful_command_records_submitted_then_completed(
        self, subprocess_run, record_stage
    ):
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
    def test_failure_message_falls_back_to_stdout_when_stderr_empty(
        self, subprocess_run, record_stage
    ):
        subprocess_run.return_value = FakeCompletedProcess(
            returncode=2, stdout="stdout details", stderr=""
        )

        with self.assertRaises(RuntimeError):
            rpd._run_stage(4, "fasttarget", "false")

        failed_call = record_stage.call_args_list[-1]
        self.assertEqual(failed_call.kwargs["status"], "failed")
        self.assertIn("stdout details", failed_call.kwargs["message"])


class RunPythonStageTests(unittest.TestCase):
    @patch("run_pipeline_direct._record_pipeline_stage")
    def test_successful_callable_records_submitted_then_completed_and_returns_value(
        self, record_stage
    ):
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

    @patch("run_pipeline_direct._record_pipeline_stage")
    def test_blocks_heavy_stage_without_flag(self, record):
        with self.assertRaises(RuntimeError) as ctx:
            rpd._assert_heavy_stage_allowed(10, "interproscan", allow_local_heavy=False)
        self.assertIn("stage 10", str(ctx.exception))
        self.assertIn("InterProScan", str(ctx.exception))
        self.assertIn("--allow-local-heavy", str(ctx.exception))
        record.assert_called_once_with(
            10, "interproscan", status="failed", message=str(ctx.exception)
        )


class PsortRoutingTests(unittest.TestCase):
    @patch("run_pipeline_direct._run_python_stage")
    @patch("run_pipeline_direct._run_stage")
    def test_stage20_routes_to_slurm(self, local, remote):
        with patch.dict(os.environ, {"TPW_PSORT_USE_REMOTE": "1"}, clear=True):
            rpd.run_genome(
                "G",
                "n",
                working_dir="/app",
                cfg_dict=None,
                start_stage=20,
                skip_stages={21, 22, 23, 24},
                allow_local_heavy=False,
            )
        local.assert_not_called()
        self.assertEqual(remote.call_args.args[:3], (20, "psort_remote", rpd.run_remote_psort))

    @patch("run_pipeline_direct._run_stage")
    def test_stage20_cannot_fall_back_to_nodo0(self, local):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, "PSORTb"):
            rpd.run_genome(
                "G",
                "n",
                working_dir="/app",
                cfg_dict=None,
                start_stage=20,
                skip_stages={21, 22, 23, 24},
                allow_local_heavy=False,
            )
        local.assert_not_called()

    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.validate_psort_file", side_effect=ValueError("incomplete PSORT"))
    @patch("run_pipeline_direct._run_stage")
    def test_stage21_refuses_loading_invalid_predictions(self, local, validate, record):
        with self.assertRaisesRegex(ValueError, "incomplete PSORT"):
            rpd.run_genome(
                "G",
                "n",
                working_dir="/app",
                cfg_dict=None,
                start_stage=21,
                skip_stages={22, 23, 24},
            )
        local.assert_not_called()
        self.assertEqual(record.call_args.kwargs["status"], "failed")

    @patch("run_pipeline_direct._run_completion_step")
    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct._run_python_stage")
    @patch("run_pipeline_direct._run_stage")
    def test_ligq_replaces_legacy_binders_when_enabled(self, local, remote, record, completion):
        with patch.dict(os.environ, {"TPW_LIGQ_USE_REMOTE": "1"}, clear=True):
            rpd.run_genome(
                "G", "n", working_dir="/app", cfg_dict=None, start_stage=22, allow_local_heavy=False
            )
        local.assert_not_called()
        self.assertEqual(remote.call_args.args[:3], (24, "ligq_remote", rpd.run_remote_ligq))
        self.assertEqual([call.args[0] for call in record.call_args_list], [22, 23])
        self.assertEqual(completion.call_args.args[:2], (24, "binder_directness"))


class CompletionStepTests(unittest.TestCase):
    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.subprocess.run")
    def test_failure_is_recorded_as_info_and_does_not_stop_the_run(self, subprocess_run, record):
        subprocess_run.return_value = MagicMock(returncode=1, stdout="", stderr="no cache")
        self.assertFalse(rpd._run_completion_step(13, "cached_annotations", "false"))
        self.assertEqual(record.call_args.kwargs["status"], "info")
        self.assertIn("no cache", record.call_args.kwargs["message"])

    @patch("run_pipeline_direct._record_pipeline_stage")
    @patch("run_pipeline_direct.subprocess.run")
    def test_success_is_recorded_as_completed(self, subprocess_run, record):
        subprocess_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        self.assertTrue(rpd._run_completion_step(3, "genbank_ec", "true"))
        self.assertEqual(record.call_args.kwargs["status"], "completed")

    @patch("run_pipeline_direct._record_pipeline_stage")
    def test_skipped_ligq_does_not_silently_omit_binders(self, record):
        with patch.dict(os.environ, {"TPW_LIGQ_USE_REMOTE": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "stage 22"):
                rpd.run_genome(
                    "G",
                    "n",
                    working_dir="/app",
                    cfg_dict=None,
                    start_stage=22,
                    skip_stages={24},
                    allow_local_heavy=False,
                )
        self.assertEqual(record.call_args.args[0], 22)
        self.assertEqual(record.call_args.kwargs["status"], "failed")


class ComputeFolderPathTests(unittest.TestCase):
    def test_splits_genome_accession_into_middle_bucket_directory(self):
        # Mirrors the on-disk layout documented in CLAUDE.md's genome reset
        # recipe -- get this math wrong and stages read/write the wrong folder.
        # "NZ_AP023069.1" is 13 chars; floor(13/2-1):floor(13/2+2) == [5:8] == "023".
        folder_path = rpd._compute_folder_path("/app/tp", "NZ_AP023069.1")
        self.assertEqual(folder_path, "/app/tp/data/023/NZ_AP023069.1")


class ResolveWorkingDirTests(unittest.TestCase):
    """The queue worker deliberately launches this script with cwd set to
    pipeline/ itself (_build_pipeline_runtime in tpweb/services/genome_uploads.py),
    so os.getcwd() is never a safe fallback here -- it silently produced
    .../pipeline/manage.py instead of .../manage.py in production
    (custom_gbk failed (rc=2): can't open file '.../pipeline/manage.py')."""

    def setUp(self):
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("TPW_PIPELINE_WORKING_DIR", None)
        self.addCleanup(self._env_patch.stop)

    def test_env_var_wins_over_everything(self):
        os.environ["TPW_PIPELINE_WORKING_DIR"] = "/from/env"
        cfg = configparser.ConfigParser()
        cfg.read_string("[GENERAL]\nWorkingDir=/from/ini\n")

        self.assertEqual(rpd._resolve_working_dir(cfg), "/from/env")

    def test_ini_wins_when_env_var_missing(self):
        cfg = configparser.ConfigParser()
        cfg.read_string("[GENERAL]\nWorkingDir=/from/ini\n")

        self.assertEqual(rpd._resolve_working_dir(cfg), "/from/ini")

    def test_falls_back_to_repo_root_not_cwd(self):
        # An empty config (e.g. settings.ini has only [SSH], no [GENERAL])
        # must still resolve to the actual project root -- the parent of
        # pipeline/ -- regardless of the process's current working directory.
        cfg = configparser.ConfigParser()

        resolved = rpd._resolve_working_dir(cfg)

        self.assertEqual(Path(resolved), _PIPELINE_DIR.parent)


if __name__ == "__main__":
    unittest.main()

"""Cover colabfold_remote.py's batched GPU pass without a live SSH/SLURM
connection: how candidates are chunked, how a batch's shared output dir is
matched back to locus tags, and that anything a batch didn't produce falls
through to the per-protein pass.

Like test_fasttarget_remote.py, this needs paramiko/scp importable
(colabfold_remote imports them transitively via slurm_remote_command) -- it
runs for real via `make test` inside the container.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import colabfold_remote as cfr  # noqa: E402


def _config(**overrides):
    defaults = dict(
        ssh_rootfolder="/home/agutson",
        ssh_host="cluster.qb.fcen.uba.ar",
        ssh_user="agutson",
        ssh_port=22,
        ssh_password=None,
        ssh_key_filename=None,
        ssh_connect_timeout=10,
        remote_poll_seconds=60,
        remote_wait_seconds=43200,
        gpu_pending_wait_seconds=0,
        cpu_pending_wait_seconds=0,
        remote_completion_grace_seconds=120,
        conda_prefix="/home/shared/miniconda3.8",
        conda_env="colabfold",
        num_recycles=3,
        num_models=1,
        max_sequence_length=800,
        gpu_slurm_partition="gpu",
        gpu_slurm_time="12:00:00",
        gpu_slurm_mem="16gb",
        gpu_slurm_gres="gpu:1",
        gpu_slurm_cpus_per_task=4,
        gpu_slurm_exclude="",
        strict_gpu=False,
        max_parallel=1,
        batch_size=3,
        cpu_catchup_max_parallel=1,
        gpu_retry_attempts=1,
        cpu_slurm_partition="cpu",
        cpu_slurm_time="24:00:00",
        cpu_slurm_mem="32gb",
        cpu_slurm_cpus_per_task=8,
        cpu_slurm_exclude="",
        cpu_retry_attempts=2,
    )
    defaults.update(overrides)
    return cfr.ColabFoldRemoteConfig(**defaults)


def _write_pdb(folder_path, locus_tag):
    path = Path(cfr._candidate_pdb_path(folder_path, locus_tag))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ATOM\n")


class MakeLengthBatchesTests(unittest.TestCase):
    def test_sorts_by_length_then_chunks(self):
        entries = [("C", "A" * 30), ("A", "A" * 10), ("D", "A" * 40), ("B", "A" * 20)]

        batches = cfr._make_length_batches(entries, 3)

        self.assertEqual([[tag for tag, _ in b] for b in batches], [["A", "B", "C"], ["D"]])

    def test_empty_input_gives_no_batches(self):
        self.assertEqual(cfr._make_length_batches([], 25), [])


class FindBatchPdbTests(unittest.TestCase):
    def test_does_not_confuse_a_tag_with_a_longer_tag_sharing_its_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in (
                "X_1_2_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb",
                "X_1_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb",
                "X_1_unrelaxed_rank_002_alphafold2_ptm_model_1_seed_000.pdb",
            ):
                Path(tmp, name).write_text("ATOM\n")

            self.assertEqual(
                os.path.basename(cfr._find_batch_pdb(tmp, "X_1")),
                "X_1_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb",
            )
            self.assertEqual(
                os.path.basename(cfr._find_batch_pdb(tmp, "X_1_2")),
                "X_1_2_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb",
            )
            self.assertIsNone(cfr._find_batch_pdb(tmp, "X_3"))


class BatchedGpuPassTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_leftovers_are_proteins_the_batches_did_not_produce(self):
        candidates = [("P1", "A" * 10), ("P2", "A" * 20), ("P3", "A" * 30), ("P4", "A" * 40)]
        submitted = []

        def fake_batch(config, run_id_raw, folder_path, genome, entries):
            submitted.append([tag for tag, _ in entries])
            saved = [tag for tag, _ in entries if tag != "P2"]  # P2's query aborted
            for tag in saved:
                _write_pdb(folder_path, tag)
            return saved

        with (
            mock.patch.object(cfr, "_run_batch_attempt", side_effect=fake_batch),
            mock.patch.object(cfr, "_record_remote_info"),
        ):
            predicted, leftovers = cfr._run_batched_gpu_pass(
                _config(batch_size=3), candidates, self.folder, "G", ""
            )

        self.assertEqual(submitted, [["P1", "P2", "P3"], ["P4"]])
        self.assertEqual(predicted, 3)
        self.assertEqual([tag for tag, _ in leftovers], ["P2"])

    def test_failed_batch_sends_all_its_proteins_to_the_per_protein_pass(self):
        candidates = [("P1", "A" * 10), ("P2", "A" * 20)]

        with (
            mock.patch.object(cfr, "_run_batch_attempt", side_effect=RuntimeError("node down")),
            mock.patch.object(cfr, "_record_remote_info") as record,
        ):
            predicted, leftovers = cfr._run_batched_gpu_pass(
                _config(batch_size=5), candidates, self.folder, "G", ""
            )

        self.assertEqual(predicted, 0)
        self.assertEqual(leftovers, candidates)
        self.assertIn("retrying them one by one", record.call_args_list[0].kwargs["message"])

    def test_too_long_proteins_skip_batching_but_stay_in_leftovers(self):
        candidates = [("SHORT", "A" * 100), ("LONG", "A" * 900)]
        submitted = []

        def fake_batch(config, run_id_raw, folder_path, genome, entries):
            submitted.append([tag for tag, _ in entries])
            for tag, _ in entries:
                _write_pdb(folder_path, tag)
            return [tag for tag, _ in entries]

        with (
            mock.patch.object(cfr, "_run_batch_attempt", side_effect=fake_batch),
            mock.patch.object(cfr, "_record_remote_info"),
        ):
            predicted, leftovers = cfr._run_batched_gpu_pass(
                _config(batch_size=5, max_sequence_length=800), candidates, self.folder, "G", ""
            )

        self.assertEqual(submitted, [["SHORT"]])
        self.assertEqual(predicted, 1)
        self.assertEqual([tag for tag, _ in leftovers], ["LONG"])


class _FakeStream:
    def __init__(self, text="", code=0):
        self._text = text
        self.channel = mock.Mock(recv_exit_status=mock.Mock(return_value=code))

    def read(self):
        return self._text.encode()


class _FakeRemote:
    """Just enough SSH/SCP/SFTP for one job whose DONE marker already exists."""

    def __init__(self, output_names):
        self.output_names = output_names
        self.written = {}
        self.uploaded = {}
        self.commands = []

    def exec_command(self, command):
        self.commands.append(command)
        out = "4242" if "sbatch" in command else ""
        return None, _FakeStream(out), _FakeStream()

    def put(self, local, remote):
        self.uploaded[remote] = Path(local).read_text()

    def file(self, path, _mode):
        remote = self

        class _Handle:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, text):
                remote.written[path] = text

        return _Handle()

    def listdir(self, _path):
        return list(self.output_names)

    def get(self, _remote, local, recursive=False):
        if not recursive:  # scp's recursive dir copy brings nothing back here
            Path(local).write_text("ATOM\n")


class RunRemoteColabfoldJobBatchTests(unittest.TestCase):
    def test_batch_job_uploads_all_queries_tolerates_partial_runs_and_saves_what_exists(self):
        remote = _FakeRemote(
            [
                "P1_unrelaxed_rank_001_alphafold2_ptm_model_1_seed_000.pdb",
                "P1_unrelaxed_rank_002_alphafold2_ptm_model_1_seed_000.pdb",
                "P1.a3m",
            ]
        )
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(cfr, "_record_remote_job"),
            mock.patch.object(cfr, "_record_remote_info"),
        ):
            saved = cfr._run_remote_colabfold_job(
                ssh=remote,
                scp_client=remote,
                sftp=remote,
                config=_config(),
                run_id_raw="",
                folder_path=folder,
                genome="public__G",
                entries=[("P1", "MKV"), ("P2", "MKVL")],
                mode="gpu",
                batch=True,
            )
            self.assertTrue(os.path.exists(cfr._candidate_pdb_path(folder, "P1")))
            self.assertFalse(os.path.exists(cfr._candidate_pdb_path(folder, "P2")))

        self.assertEqual(saved, ["P1"])
        (fasta,) = remote.uploaded.values()
        self.assertEqual(fasta, ">P1\nMKV\n>P2\nMKVL\n")
        runner = next(text for path, text in remote.written.items() if path.endswith(".sh"))
        self.assertIn('|| echo "colabfold_batch exited with status $?"', runner)
        slurm = next(text for path, text in remote.written.items() if path.endswith(".slurm"))
        self.assertIn("#SBATCH --gres=gpu:1", slurm)

    def test_single_protein_runner_still_fails_hard(self):
        remote = _FakeRemote([])
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(cfr, "_record_remote_job"),
            mock.patch.object(cfr, "_record_remote_info"),
            self.assertRaises(RuntimeError),
        ):
            cfr._run_remote_colabfold_candidate(
                ssh=remote,
                scp_client=remote,
                sftp=remote,
                config=_config(),
                run_id_raw="",
                folder_path=folder,
                genome="public__G",
                locus_tag="P1",
                sequence="MKV",
                mode="gpu",
            )

        runner = next(text for path, text in remote.written.items() if path.endswith(".sh"))
        self.assertNotIn("|| echo", runner)


class RunRemoteColabfoldBatchSwitchTests(unittest.TestCase):
    def _run(self, batch_size, batch_result=None):
        candidates = [("P1", "A" * 10), ("P2", "A" * 20)]
        with (
            mock.patch.object(
                cfr, "_build_colabfold_config", return_value=_config(batch_size=batch_size)
            ),
            mock.patch.object(cfr, "_find_candidates", return_value=candidates),
            mock.patch.object(cfr, "_assert_ssh_reachable"),
            mock.patch.object(cfr, "_run_batched_gpu_pass", return_value=batch_result) as batched,
            mock.patch.object(
                cfr, "_process_candidate_gpu_phase", return_value=None
            ) as per_protein,
        ):
            predicted = cfr.run_remote_colabfold({}, "/tmp/unused", "G")
        return predicted, batched, per_protein

    def test_batch_size_one_keeps_the_one_job_per_protein_path(self):
        predicted, batched, per_protein = self._run(batch_size=1)

        batched.assert_not_called()
        self.assertEqual(per_protein.call_count, 2)
        self.assertEqual(predicted, 2)

    def test_batch_leftovers_go_through_the_per_protein_pass(self):
        predicted, batched, per_protein = self._run(
            batch_size=25, batch_result=(1, [("P2", "A" * 20)])
        )

        batched.assert_called_once()
        self.assertEqual([c.args[1] for c in per_protein.call_args_list], ["P2"])
        self.assertEqual(predicted, 2)

    def test_nothing_left_after_batches_skips_the_per_protein_pass(self):
        predicted, _batched, per_protein = self._run(batch_size=25, batch_result=(2, []))

        per_protein.assert_not_called()
        self.assertEqual(predicted, 2)


if __name__ == "__main__":
    unittest.main()

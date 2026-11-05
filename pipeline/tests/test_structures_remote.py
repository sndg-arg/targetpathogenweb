"""Cover structures_remote.py's stage-17 parallelism without SSH/SLURM: the
sbatch script runs one protein per worker instead of a sequential loop, and
the local DB import fans out over several workers while keeping its counts.

Needs paramiko/scp importable (via slurm_remote_command) -- runs for real via
`make test` inside the container.
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

import structures_remote as sr  # noqa: E402


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
        remote_wait_seconds=259200,
        slurm_partition="cpu",
        slurm_time="48:00:00",
        slurm_mem="32G",
        slurm_cpus_per_task=8,
        slurm_exclude="",
        remote_setup="",
        fpocket_bin="fpocket",
        p2rank_bin="prank",
    )
    defaults.update(overrides)
    return sr.StructuresRemoteConfig(**defaults)


class BuildSlurmScriptTests(unittest.TestCase):
    def test_runs_one_protein_per_worker_across_all_cpus(self):
        script = sr._build_slurm_script(_config(), "/w/in.tar", "/w/out.tar", "/w")

        self.assertIn("#SBATCH --cpus-per-task=8", script)
        self.assertIn("export -f process_one", script)
        self.assertIn('xargs -0 -r -n 1 -P "${THREADS}"', script)
        self.assertIn("-threads 1", script)
        self.assertNotIn("while IFS= read", script)

    def test_counts_come_from_per_protein_markers_not_shared_variables(self):
        # Counters incremented inside parallel subshells would always read 0.
        script = sr._build_slurm_script(_config(), "/w/in.tar", "/w/out.tar", "/w")

        self.assertIn('fpocket_ok=$(find "${STATUS}" -name "*.fpocket" | wc -l)', script)
        self.assertIn('p2rank_ok=$(find "${STATUS}" -name "*.p2rank" | wc -l)', script)


class PostprocessOutputsTests(unittest.TestCase):
    def test_imports_every_protein_in_parallel_and_keeps_counts(self):
        loci = [f"L{i}" for i in range(10)]
        calls = []

        def fake_run(command, label):
            calls.append(label)
            if label == "load_p2pocket L3":
                raise RuntimeError("boom")

        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(sr, "_existing_loaded_structures", return_value={"L0"}),
            mock.patch.object(sr, "_run_local_command", side_effect=fake_run),
            mock.patch.dict(os.environ, {"TPW_STRUCTURES_IMPORT_WORKERS": "4"}),
        ):
            for name in (
                "load_af_model_cmd",
                "fpocket2json_cmd",
                "load_pocket_cmd",
                "p2rank2json_cmd",
                "load_p2pocket_cmd",
            ):
                patcher = mock.patch.object(sr, name, return_value="true")
                patcher.start()
                self.addCleanup(patcher.stop)
            for locus in ("L1", "L2"):  # only these have fpocket JSON
                out = Path(folder, "alphafold", locus, f"{locus}_af_out")
                out.mkdir(parents=True)
                (out / "fpocket.json.gz").write_text("{}")

            fpocket, p2rank, errors = sr._postprocess_outputs(loci, "G", "/wd", folder)

        self.assertEqual(fpocket, 2)
        self.assertEqual(p2rank, 9)
        self.assertEqual([locus for locus, _ in errors], ["L3"])
        self.assertNotIn("load_af_model L0", calls)  # already loaded: skipped
        self.assertEqual(sum(c.startswith("load_af_model") for c in calls), 9)


if __name__ == "__main__":
    unittest.main()

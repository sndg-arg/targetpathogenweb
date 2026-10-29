"""LigQ prefix environments must work without the base Conda installation."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import ligq_remote as lr  # noqa: E402


def _config(**overrides):
    values = dict(
        conda_prefix="/missing/base-conda",
        conda_env="/home/agutson/work/conda_envs/ligq_2_local",
        slurm_partition="cpu",
        slurm_exclude="",
        slurm_cpus_per_task=8,
        slurm_time="48:00:00",
        slurm_mem="32G",
        ligq_dir="/home/agutson/work/LigQ_2",
        ligq_data_dir="/home/agutson/work/ligq_data",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class LigqEnvironmentTests(unittest.TestCase):
    def test_prefix_uses_own_python_and_exposes_tools_without_base_conda(self):
        script = lr._build_slurm_script(_config(), "/w/in.fa", "/w/out", "/w")
        self.assertNotIn("/missing/base-conda", script)
        self.assertNotIn("conda activate", script)
        self.assertIn("/home/agutson/work/conda_envs/ligq_2_local/bin/python", script)
        self.assertIn('export PATH=/home/agutson/work/conda_envs/ligq_2_local/bin:"$PATH"', script)
        self.assertIn("export CONDA_PREFIX=/home/agutson/work/conda_envs/ligq_2_local", script)

    def test_named_environment_keeps_conda_activation(self):
        script = lr._build_slurm_script(_config(conda_env="ligq_named"), "/w/in.fa", "/w/out", "/w")
        self.assertIn("source /missing/base-conda/etc/profile.d/conda.sh", script)
        self.assertIn("conda activate ligq_named", script)
        self.assertIn('python "/home/agutson/work/LigQ_2/run_ligq_2.py"', script)

    def test_prefix_with_spaces_is_shell_quoted(self):
        script = lr._build_slurm_script(
            _config(conda_env="/envs/ligq local/"), "/w/in.fa", "/w/out", "/w"
        )
        self.assertIn("'/envs/ligq local/bin/python'", script)
        self.assertIn("export PATH='/envs/ligq local/bin':\"$PATH\"", script)
        self.assertIn("export CONDA_PREFIX='/envs/ligq local'", script)

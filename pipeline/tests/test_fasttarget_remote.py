"""Cover fasttarget_remote.py's pure logic: the sbatch script it hands to
SLURM, and the gz-on-demand GBK unzip fast_command.py itself also does.
Neither needs a live SSH/SLURM connection, but a wrong sbatch script (a typo
in the embedded Python, a missing --mem, the wrong conda env name) would
otherwise only surface after a real remote job fails.

Like test_run_pipeline_direct.py, this can't be executed in an environment
without paramiko/scp installed (fasttarget_remote imports them transitively
via slurm_remote_command) -- it runs for real via `make test` inside the
container, where they are.
"""

import sys
import unittest
from pathlib import Path

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import fasttarget_remote as ftr  # noqa: E402


def _config(**overrides):
    defaults = dict(
        ssh_rootfolder="/home/agutson",
        ssh_host="cluster.qb.fcen.uba.ar",
        ssh_user="agutson",
        ssh_port=22,
        ssh_password=None,
        ssh_key_filename=None,
        ssh_connect_timeout=10,
        remote_poll_seconds=30,
        remote_wait_seconds=21600,
        conda_prefix="/home/shared/miniconda3.8",
        conda_env="fasttarget",
        fasttarget_dir="/home/agutson/fasttarget",
        databases_dir="/home/agutson/fasttarget_databases",
        slurm_partition="cpu",
        slurm_time="02:00:00",
        slurm_mem="8G",
        slurm_cpus_per_task=4,
        slurm_exclude="",
    )
    defaults.update(overrides)
    return ftr.FastTargetRemoteConfig(**defaults)


class BuildSlurmScriptTests(unittest.TestCase):
    def test_includes_sbatch_directives_from_config(self):
        script = ftr._build_slurm_script(
            _config(), genome="GCA_TEST01", remote_workdir="/home/agutson/tpw_fasttarget/x"
        )

        self.assertIn("#SBATCH -p cpu", script)
        self.assertIn("#SBATCH --cpus-per-task=4", script)
        self.assertIn("#SBATCH --time=02:00:00", script)
        self.assertIn("#SBATCH --mem=8G", script)
        self.assertIn("#SBATCH --chdir=/home/agutson/tpw_fasttarget/x", script)

    def test_activates_the_configured_conda_env(self):
        script = ftr._build_slurm_script(
            _config(conda_env="my_custom_env"), genome="GCA_TEST01", remote_workdir="/tmp/x"
        )

        self.assertIn('conda activate "my_custom_env"', script)

    def test_includes_exclude_only_when_configured(self):
        without_exclude = ftr._build_slurm_script(
            _config(), genome="GCA_TEST01", remote_workdir="/tmp/x"
        )
        self.assertNotIn("--exclude", without_exclude)

        with_exclude = ftr._build_slurm_script(
            _config(slurm_exclude="nodo3,nodo7"), genome="GCA_TEST01", remote_workdir="/tmp/x"
        )
        self.assertIn("#SBATCH --exclude=nodo3,nodo7", with_exclude)

    def test_embedded_python_calls_search_then_parse_in_order(self):
        script = ftr._build_slurm_script(_config(), genome="GCA_TEST01", remote_workdir="/tmp/x")

        search_calls = [
            "offtargets.human_offtarget_blast(",
            "offtargets.microbiome_offtarget_blast_species(",
            "essentiality.essential_deg_blast(",
        ]
        parse_calls = [
            "offtargets.human_offtarget_parse(",
            "offtargets.microbiome_species_parse(",
            "essentiality.deg_parse(",
        ]
        for call in search_calls + parse_calls:
            self.assertIn(call, script)

        # Parsing reads the search output, so it must come strictly after it.
        last_search_index = max(script.index(call) for call in search_calls)
        first_parse_index = min(script.index(call) for call in parse_calls)
        self.assertLess(last_search_index, first_parse_index)

    def test_embeds_the_genome_name_and_remote_paths(self):
        script = ftr._build_slurm_script(
            _config(databases_dir="/home/agutson/fasttarget_databases"),
            genome="GCA_TEST01",
            remote_workdir="/home/agutson/tpw_fasttarget/GCA_TEST01_20260101",
        )

        self.assertIn("organism_name = 'GCA_TEST01'", script)
        self.assertIn("output_path = '/home/agutson/tpw_fasttarget/GCA_TEST01_20260101'", script)
        self.assertIn("databases_path = '/home/agutson/fasttarget_databases'", script)

    def test_touches_done_marker_after_the_python_script_runs(self):
        script = ftr._build_slurm_script(_config(), genome="GCA_TEST01", remote_workdir="/tmp/x")

        run_index = script.index("python run_fasttarget.py")
        done_index = script.index('touch "/tmp/x/DONE"')
        self.assertLess(run_index, done_index)


class EnsureLocalGbkTests(unittest.TestCase):
    def test_uses_existing_gbk_without_decompressing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            gbk_path = Path(tmpdir) / "GCA_TEST01.gbk"
            gbk_path.write_text("LOCUS fake\n")

            result = ftr._ensure_local_gbk(tmpdir, "GCA_TEST01")

            self.assertEqual(result, str(gbk_path))
            self.assertEqual(gbk_path.read_text(), "LOCUS fake\n")

    def test_decompresses_gz_when_plain_gbk_is_missing(self):
        import gzip
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            gz_path = Path(tmpdir) / "GCA_TEST01.gbk.gz"
            with gzip.open(gz_path, "wb") as handle:
                handle.write(b"LOCUS fake\n")

            result = ftr._ensure_local_gbk(tmpdir, "GCA_TEST01")

            self.assertEqual(result, str(Path(tmpdir) / "GCA_TEST01.gbk"))
            self.assertEqual(Path(result).read_bytes(), b"LOCUS fake\n")


if __name__ == "__main__":
    unittest.main()

"""Pin the exact bash command each pipeline stage builder emits.

pipeline_commands.py has zero test coverage today even though it's the part
of the orchestrator most likely to silently break a stage: a wrong flag here
doesn't fail until the command actually runs against real data (e.g. the
`-b` vs `-o`/`-d` InterProScan flag mixup documented in CLAUDE.md). These
tests assert the literal command string per stage so a regression like that
shows up in CI instead of on the cluster.
"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

_PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import pipeline_commands as pc  # noqa: E402


class DataDirHelperTests(unittest.TestCase):
    def test_data_dir_joins_working_dir(self):
        self.assertEqual(pc._data_dir("/app/targetpathogenweb"), "/app/targetpathogenweb/data")


class HostBindPathTests(unittest.TestCase):
    def test_returns_container_path_when_no_host_base_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            result = pc._host_bind_path(
                "/app/targetpathogenweb/data/foo",
                env_name="TPW_DATA_DIR",
                container_base="/app/targetpathogenweb/data",
            )
        self.assertEqual(result, "/app/targetpathogenweb/data/foo")

    def test_remaps_container_path_under_host_base(self):
        with patch.dict(os.environ, {"TPW_DATA_DIR": "/mnt/host/data"}, clear=True):
            result = pc._host_bind_path(
                "/app/targetpathogenweb/data/ABC/genome1",
                env_name="TPW_DATA_DIR",
                container_base="/app/targetpathogenweb/data",
            )
        self.assertEqual(result, os.path.join("/mnt/host/data", "ABC", "genome1"))

    def test_leaves_paths_outside_container_base_untouched(self):
        with patch.dict(os.environ, {"TPW_DATA_DIR": "/mnt/host/data"}, clear=True):
            result = pc._host_bind_path(
                "/somewhere/else/foo",
                env_name="TPW_DATA_DIR",
                container_base="/app/targetpathogenweb/data",
            )
        self.assertEqual(result, "/somewhere/else/foo")


class GenomeDownloadCommandTests(unittest.TestCase):
    def test_download_gbk_cmd_without_target_accession(self):
        cmd = pc.download_gbk_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py tpweb_download_gbk NZ_AP023069.1 --datadir /app/tp/data",
        )
        self.assertNotIn("--target-accession", cmd)

    def test_download_gbk_cmd_with_target_accession(self):
        cmd = pc.download_gbk_cmd("/app/tp", "NZ_AP023069.1", target_accession="GCF_000001")
        self.assertTrue(cmd.endswith("--target-accession GCF_000001"))

    def test_test_gbk_cmd(self):
        cmd = pc.test_gbk_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py tpweb_test_gbk --datadir /app/tp/data --target-accession NZ_AP023069.1",
        )

    def test_custom_gbk_cmd(self):
        cmd = pc.custom_gbk_cmd("/app/tp", "NZ_AP023069.1", "/tmp/custom.gbk")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py custom_gbk NZ_AP023069.1 --datadir /app/tp/data --custom /tmp/custom.gbk",
        )


class LoadGbkCommandTests(unittest.TestCase):
    def test_load_gbk_cmd_builds_path_from_folder_and_genome(self):
        cmd = pc.load_gbk_cmd("/app/tp", "/app/tp/data/ABC/NZ_AP023069.1", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py load_gbk "
            "/app/tp/data/ABC/NZ_AP023069.1/NZ_AP023069.1.gbk.gz "
            "--overwrite --accession NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_sync_genome_metadata_cmd(self):
        cmd = pc.sync_genome_metadata_cmd("/app/tp", "/app/tp/data/ABC/NZ_AP023069.1", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py sync_genome_metadata NZ_AP023069.1 "
            "/app/tp/data/ABC/NZ_AP023069.1/NZ_AP023069.1.gbk.gz",
        )


class SimpleManageCommandBuildersTests(unittest.TestCase):
    """Stage builders that are a straight `manage.py <cmd> <args>` with no
    branching -- one representative assertion per stage is enough to catch a
    typo'd flag or argument order regression."""

    def test_fasttarget_cmd(self):
        cmd = pc.fasttarget_cmd("/app/tp", "NZ_AP023069.1", "/app/tp/data/ABC/NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py fast_command NZ_AP023069.1 "
            "/app/tp/data/ABC/NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_index_db_cmd(self):
        cmd = pc.index_db_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py index_genome_db NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_index_seq_cmd(self):
        cmd = pc.index_seq_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py index_genome_seq_clean NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_load_interpro_cmd(self):
        cmd = pc.load_interpro_cmd("/app/tp", "NZ_AP023069.1", "/app/tp/data/ABC/NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py load_interpro NZ_AP023069.1 "
            "--interpro_tsv /app/tp/data/ABC/NZ_AP023069.1/NZ_AP023069.1.faa.tsv",
        )

    def test_gbk2uniprot_cmd_redirects_stdout_to_unips_lst(self):
        cmd = pc.gbk2uniprot_cmd("/app/tp", "NZ_AP023069.1", "/app/tp/data/ABC/NZ_AP023069.1")
        self.assertIn("gbk2uniprot_map NZ_AP023069.1 --batch_size 300", cmd)
        self.assertTrue(cmd.endswith("> /app/tp/data/ABC/NZ_AP023069.1/NZ_AP023069.1_unips.lst"))

    def test_fetch_annotations_cmd(self):
        cmd = pc.fetch_annotations_cmd("/app/tp", "NZ_AP023069.1", "/app/tp/data/ABC/NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py fetch_uniprot_annotations NZ_AP023069.1 "
            "--datadir /app/tp/data "
            "--lst /app/tp/data/ABC/NZ_AP023069.1/NZ_AP023069.1_unips.lst",
        )

    def test_load_uniprot_sites_cmd_overwrites(self):
        cmd = pc.load_uniprot_sites_cmd("/app/tp", "NZ_AP023069.1", "/app/tp/data/ABC/NZ_AP023069.1")
        self.assertIn("load_uniprot_sites NZ_AP023069.1", cmd)
        self.assertIn("--overwrite", cmd)

    def test_alphafold_cmd_parses_accession_and_locustag_from_line(self):
        cmd = pc.alphafold_cmd("locus_a P12345 extra_ignored", "/app/tp/data/ABC/g1", "g1")
        self.assertIn("-o /app/tp/data/ABC/g1/alphafold", cmd)
        self.assertIn("-parsl locus_a -ltag P12345", cmd)

    def test_colabfold_cmd(self):
        cmd = pc.colabfold_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py colabfold_predict NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_load_af_model_cmd(self):
        cmd = pc.load_af_model_cmd("locus_a", "/app/tp", "/app/tp/data/ABC/g1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py load_af_model locus_a "
            "/app/tp/data/ABC/g1/alphafold/locus_a/locus_a_af.pdb "
            "locus_a --overwrite --datadir /app/tp/data",
        )

    def test_druggability_cmd(self):
        cmd = pc.druggability_cmd("/app/tp", "NZ_AP023069.1")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py druggability_2_csv NZ_AP023069.1 --datadir /app/tp/data",
        )

    def test_get_binders_cmd(self):
        cmd = pc.get_binders_cmd("/app/tp", "NZ_AP023069.1")
        self.assertIn("get_binders NZ_AP023069.1", cmd)

    def test_load_binders_cmd(self):
        cmd = pc.load_binders_cmd("/app/tp", "NZ_AP023069.1")
        self.assertIn("load_binders NZ_AP023069.1", cmd)


class FpocketStageCommandTests(unittest.TestCase):
    """These branch on filesystem state (does the AF PDB / fpocket output
    already exist), which is exactly the kind of conditional logic that's
    easy to get backwards."""

    def test_run_fpocket_cmd_skips_when_no_pdb_present(self):
        with TemporaryDirectory() as folder_path:
            cmd = pc.run_fpocket_cmd(folder_path, "locus_a")
        self.assertIn("No structure PDB for locus_a, skipping fpocket", cmd)

    def test_run_fpocket_cmd_invokes_docker_when_pdb_present(self):
        with TemporaryDirectory() as folder_path:
            locus_dir = Path(folder_path) / "alphafold" / "locus_a"
            locus_dir.mkdir(parents=True)
            (locus_dir / "locus_a_af.pdb").write_text("HEADER\n")

            with patch.dict(os.environ, {}, clear=True):
                cmd = pc.run_fpocket_cmd(folder_path, "locus_a")

        self.assertIn("fpocket -f /work/locus_a_af.pdb", cmd)
        self.assertIn("ezequieljsosa/fpocket", cmd)

    def test_fpocket2json_cmd_skips_when_no_fpocket_output(self):
        with TemporaryDirectory() as folder_path:
            cmd = pc.fpocket2json_cmd(folder_path, "locus_a")
        self.assertIn("No fpocket output for locus_a, skipping", cmd)

    def test_fpocket2json_cmd_converts_when_output_present(self):
        with TemporaryDirectory() as folder_path:
            out_dir = Path(folder_path) / "alphafold" / "locus_a" / "locus_a_af_out"
            out_dir.mkdir(parents=True)
            cmd = pc.fpocket2json_cmd(folder_path, "locus_a")
        self.assertIn("SNDG.Structure.FPocket 2json", cmd)
        self.assertTrue(cmd.rstrip().endswith("fpocket.json.gz"))

    def test_load_pocket_cmd_skips_when_no_fpocket_json(self):
        with TemporaryDirectory() as folder_path:
            cmd = pc.load_pocket_cmd(folder_path, "locus_a", "/app/tp")
        self.assertIn("No fpocket data for locus_a, skipping", cmd)

    def test_load_pocket_cmd_loads_when_fpocket_json_present(self):
        with TemporaryDirectory() as folder_path:
            out_dir = Path(folder_path) / "alphafold" / "locus_a" / "locus_a_af_out"
            out_dir.mkdir(parents=True)
            (out_dir / "fpocket.json.gz").write_bytes(b"")
            cmd = pc.load_pocket_cmd(folder_path, "locus_a", "/app/tp")
        self.assertIn("load_fpocket --pocket_json", cmd)
        self.assertIn("locus_a --datadir /app/tp/data", cmd)


class P2rankToJsonCommandTests(unittest.TestCase):
    def test_p2rank2json_cmd(self):
        cmd = pc.p2rank2json_cmd("NZ_AP023069.1", "locus_a", "/app/tp")
        self.assertEqual(
            cmd,
            f"{pc.PYTHON_BIN} /app/tp/manage.py p2rank_2_json NZ_AP023069.1 locus_a --datadir /app/tp/data",
        )


class PsortCommandTests(unittest.TestCase):
    """psort_cmd builds a docker-wrapped shell script -- assert the gram
    flag and the Docker/fallback branching are both wired correctly."""

    def test_psort_cmd_embeds_gram_flag_and_docker_image(self):
        with patch.dict(os.environ, {}, clear=True):
            cmd = pc.psort_cmd("NZ_AP023069.1", "n")
        self.assertIn("brinkmanlab/psortb_commandline:1.0.2", cmd)
        self.assertIn("psort -n -o terse", cmd)
        self.assertIn("if command -v docker", cmd)
        self.assertIn("TPW_PSORT_ALLOW_FALLBACK", cmd)

    def test_psort_cmd_positive_gram_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            cmd = pc.psort_cmd("NZ_AP023069.1", "p")
        self.assertIn("psort -p -o terse", cmd)


if __name__ == "__main__":
    unittest.main()

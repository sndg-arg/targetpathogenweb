"""Transfer safety and remote inventory selection without Django or SSH."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from human_target.services.alphafill_transfer import (
    REMOTE_INVENTORY,
    stage_file,
    validate_model_path,
)


class InventoryTests(unittest.TestCase):
    def test_chooses_newest_version_and_matches_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "P0").mkdir()
            (root / "LICENSE.txt").write_text("license")
            for name in (
                "AF-P07203-F1-filled_v4.cif.gz",
                "AF-P07203-F1-filled_v10.cif.gz",
                "AF-P07203-F2-filled_v12.cif.gz",
            ):
                (root / "P0" / name).write_bytes(b"model")
            (root / "P0/AF-P07203-F1-filled_v10.cif.json").write_text("{}")
            (root / "AF-O00116-F1-filled_v4.cif.gz").write_bytes(b"other")
            result = subprocess.run(
                [sys.executable, "-c", REMOTE_INVENTORY, str(root)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            inventory = json.loads(result.stdout)
            self.assertEqual(inventory["license_size"], 7)
            self.assertEqual(
                inventory["models"],
                [
                    ["O00116", "AF-O00116-F1-filled_v4.cif.gz", 5, None],
                    ["P07203", "P0/AF-P07203-F1-filled_v10.cif.gz", 5, 2],
                ],
            )

    def test_rejects_unexpected_paths(self):
        for path in (
            "../AF-P07203-F1-filled_v4.cif.gz",
            "/AF-P07203-F1-filled_v4.cif.gz",
            "O0/AF-P07203-F1-filled_v4.cif.gz",
            "P0/AF-O00116-F1-filled_v4.cif.gz",
            "P0/AF-P07203-F2-filled_v4.cif.gz",
            "P0//AF-P07203-F1-filled_v4.cif.gz",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_model_path("P07203", path)

    def test_accepts_flat_and_sharded_models(self):
        for path in ("AF-P07203-F1-filled_v4.cif.gz", "P0/AF-P07203-F1-filled_v4.cif.gz"):
            self.assertEqual(str(validate_model_path("P07203", path)), path)


class _Sftp:
    def __init__(self, data=b"complete", fail=False):
        self.data = data
        self.fail = fail
        self.calls = 0

    def get(self, remote, local):
        self.calls += 1
        Path(local).write_bytes(self.data)
        if self.fail:
            raise OSError("connection interrupted")


class StageFileTests(unittest.TestCase):
    def test_reuses_complete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "model.cif.gz")
            path.write_bytes(b"complete")
            sftp = _Sftp()
            self.assertFalse(stage_file(sftp, "remote", path, 8))
            self.assertEqual(sftp.calls, 0)

    def test_retry_replaces_partial_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "P0/model.cif.gz")
            path.parent.mkdir()
            path.with_name(path.name + ".part").write_bytes(b"old fragment")
            self.assertTrue(stage_file(_Sftp(), "remote", path, 8))
            self.assertEqual(path.read_bytes(), b"complete")
            self.assertFalse(path.with_name(path.name + ".part").exists())

    def test_short_transfer_preserves_existing_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "model.cif.gz")
            path.write_bytes(b"previous")
            with self.assertRaisesRegex(ValueError, "Incomplete transfer"):
                stage_file(_Sftp(b"short"), "remote", path, 10)
            self.assertEqual(path.read_bytes(), b"previous")

    def test_interruption_does_not_create_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "model.cif.gz")
            with self.assertRaises(OSError):
                stage_file(_Sftp(fail=True), "remote", path, 8)
            self.assertFalse(path.exists())

    def test_empty_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sftp = _Sftp()
            with self.assertRaisesRegex(ValueError, "Invalid source size"):
                stage_file(sftp, "remote", Path(tmp, "model.cif.gz"), 0)
            self.assertEqual(sftp.calls, 0)

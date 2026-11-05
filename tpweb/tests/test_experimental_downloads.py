import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from tpweb.services import experimental_structures as service


class ExperimentalDownloadTests(unittest.TestCase):
    def test_uses_native_cif_after_missing_pdb(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(service, "_download_pdb", side_effect=[False, True]) as download:
                path, downloaded = service._experimental_file("4YBB", folder)
            self.assertEqual(path, os.path.join(folder, "4YBB.cif"))
            self.assertTrue(downloaded)
            self.assertEqual(download.call_args_list[0].args[1], os.path.join(folder, "4YBB.pdb"))
            self.assertEqual(download.call_args_list[1].args[1], path)

    def test_cached_cif_prevents_repeated_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "4YBB.cif")
            with open(path, "w") as handle:
                handle.write("data_4YBB\n" + "#" * 200)
            with patch.object(service, "_download_pdb") as download:
                self.assertEqual(service._experimental_file("4YBB", folder), (path, False))
            download.assert_not_called()

    def test_both_formats_missing_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(service, "_download_pdb", return_value=False):
                self.assertEqual(service._experimental_file("NONE", folder), (None, False))

    def test_download_keeps_cif_content_and_extension(self):
        response = Mock(status_code=200)
        content = b"data_4YBB\n" + b"#" * 200
        response.iter_content.return_value = [content]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "4YBB.cif")
            with patch.object(service.requests, "get", return_value=response) as get:
                self.assertTrue(service._download_pdb("4ybb", path))
            self.assertEqual(get.call_args.args[0], "https://files.rcsb.org/download/4YBB.cif")
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), content)

    def test_truncated_file_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "4YBB.pdb"), "w") as handle:
                handle.write("broken")
            with patch.object(service, "_download_pdb", side_effect=[False, True]) as download:
                self.assertTrue(service._experimental_file("4YBB", folder)[1])
            self.assertEqual(download.call_count, 2)

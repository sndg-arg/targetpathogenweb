import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests


spec = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).with_name("recover_experimental_by_sequence.py")
)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def test_rejects_historical_accession_with_changed_sequence(self):
        exact = {"sequence": {"value": "MACDE"}, "primaryAccession": "current"}
        historical = {"sequence": {"value": "MACDF"}, "primaryAccession": "changed"}
        self.assertEqual(recovery.exact_matches([exact, historical], {"MACDE"}), [exact])

    def test_normalization_preserves_selenocysteine(self):
        self.assertEqual(recovery.normalize(" mau* "), "MAU")
        self.assertEqual(recovery.exact_matches([{"sequence": {"value": "MAX"}}], {"MAU"}), [])

    def test_pagination_and_checkpoint_avoid_repeated_requests(self):
        first = Mock()
        first.json.return_value = {"results": [{"uniParcId": "one"}]}
        first.links = {"next": {"url": recovery.API + "/uniparc/search?cursor=next"}}
        last = Mock()
        last.json.return_value = {"results": [{"uniParcId": "two"}]}
        last.links = {}
        session = Mock()
        session.get.side_effect = [first, last]
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            result = recovery.search(session, "uniparc", "checksum:test", cache)
            self.assertEqual(len(result), 2)
            self.assertEqual(recovery.search(session, "uniparc", "checksum:test", cache), result)
            self.assertEqual(session.get.call_count, 2)

    def test_http_failure_does_not_cache_empty_success(self):
        session = Mock()
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(requests.HTTPError):
                recovery.search(session, "uniparc", "checksum:test", Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_valid_empty_result_is_cached(self):
        session = Mock()
        session.get.return_value.json.return_value = {"results": []}
        session.get.return_value.links = {}
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            self.assertEqual(recovery.search(session, "uniprotkb", "uniparc:test", cache), [])
            self.assertEqual(recovery.search(session, "uniprotkb", "uniparc:test", cache), [])
            session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()

"""Tests for two Command-class helper methods that don't need self/DB
state beyond what's passed in explicitly."""

import gzip
import json
import os
import tempfile

from django.test import SimpleTestCase

from bioseq.io.SeqStore import SeqStore
from tpweb.management.commands.p2rank_2_json import Command as P2RankToJsonCommand
from tpweb.management.commands.druggability_2_csv import Command as DruggabilityCommand


class WriteEmptyOutputTests(SimpleTestCase):
    def test_writes_empty_json_and_gzip_pocket_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            seqstore = SeqStore(tmp)
            command = P2RankToJsonCommand()

            command._write_empty_output(seqstore, "NZ_AP023069.1", "LOCUS_A", "no output")

            output_dir = seqstore.p2rank_folder("NZ_AP023069.1", "LOCUS_A")
            json_path = os.path.join(output_dir, "p2pocket.json")
            self.assertTrue(os.path.exists(json_path))
            with open(json_path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])
            self.assertTrue(os.path.exists(json_path + ".gz"))
            with gzip.open(json_path + ".gz", "rt", encoding="utf-8") as f:
                self.assertEqual(json.load(f), [])


class DruggabilityValuesTests(SimpleTestCase):
    def test_empty_links_returns_empty_list_without_touching_the_db(self):
        command = DruggabilityCommand()
        self.assertEqual(command._druggability_values([], property_instance=None), [])

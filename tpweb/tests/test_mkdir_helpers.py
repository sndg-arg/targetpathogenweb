"""Tests for the identical mkdir(dirpath) helper duplicated across five
load_* management commands. Per tpw-django-patterns's "grep every call
site before deduplicating a copy-pasted helper" note: these are confirmed
byte-identical (a plain os.makedirs-if-missing), so one shared assertion
per import is enough -- this is about closing the coverage gap on each
file, not hunting for a behavioral difference like the backfill commands
had.
"""

import os
import tempfile

from django.test import SimpleTestCase

from tpweb.management.commands.load_af_model import mkdir as load_af_model_mkdir
from tpweb.management.commands.load_features import mkdir as load_features_mkdir
from tpweb.management.commands.load_fpocket import mkdir as load_fpocket_mkdir
from tpweb.management.commands.load_residueset import mkdir as load_residueset_mkdir
from tpweb.management.commands.load_score_values import mkdir as load_score_values_mkdir


class MkdirHelperTests(SimpleTestCase):
    def _assert_creates_missing_dir(self, mkdir_fn):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "nested", "dir")
            self.assertFalse(os.path.exists(target))
            mkdir_fn(target)
            self.assertTrue(os.path.isdir(target))
            # Calling again on an already-existing dir must not raise.
            mkdir_fn(target)

    def test_load_af_model_mkdir(self):
        self._assert_creates_missing_dir(load_af_model_mkdir)

    def test_load_features_mkdir(self):
        self._assert_creates_missing_dir(load_features_mkdir)

    def test_load_fpocket_mkdir(self):
        self._assert_creates_missing_dir(load_fpocket_mkdir)

    def test_load_residueset_mkdir(self):
        self._assert_creates_missing_dir(load_residueset_mkdir)

    def test_load_score_values_mkdir(self):
        self._assert_creates_missing_dir(load_score_values_mkdir)

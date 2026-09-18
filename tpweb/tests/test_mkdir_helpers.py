"""Test for the mkdir(dirpath) helper. Used to be copy-pasted byte-identical
across five load_* management commands (none of which actually called their
own copy -- confirmed dead code, only ever exercised from here) and has
since been consolidated into tpweb/management/commands/_shared.py, reused
by all five via import.
"""

import os
import tempfile

from django.test import SimpleTestCase

from tpweb.management.commands._shared import mkdir


class MkdirHelperTests(SimpleTestCase):
    def test_creates_missing_nested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "nested", "dir")
            self.assertFalse(os.path.exists(target))
            mkdir(target)
            self.assertTrue(os.path.isdir(target))

    def test_calling_again_on_existing_dir_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "nested", "dir")
            mkdir(target)
            mkdir(target)

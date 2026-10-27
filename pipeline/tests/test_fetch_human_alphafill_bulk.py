"""Exercise the AlphaFill downloader's manifests without network access."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BASH = (
    str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
    if os.name == "nt"
    else shutil.which("bash")
)


@unittest.skipUnless(_BASH and Path(_BASH).is_file(), "Bash is required")
class AlphaFillDownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.wrapper = self.root / "mock.sh"
        self.wrapper.write_text(
            """set -euo pipefail
rsync() {
    local arg count manifest=''
    count=$(find "$CAPTURE_DIR" -name 'args.*' | wc -l)
    printf '%s\\n' "$@" > "$CAPTURE_DIR/args.$count"
    for arg in "$@"; do
        case "$arg" in --files-from=*) manifest=${arg#--files-from=};; esac
    done
    test -n "$manifest"
    cp "$manifest" "$CAPTURE_DIR/manifest.$count"
    return "${MOCK_RSYNC_EXIT:-0}"
}
export -f rsync
bash "$@"
""",
            encoding="utf-8",
            newline="\n",
        )

    def run_script(self, accessions, **overrides):
        source = self.root / "accessions.txt"
        source.write_bytes(accessions.encode())
        env = os.environ.copy()
        env.pop("TPW_ALPHAFILL_VERSIONS", None)
        env.update(CAPTURE_DIR=self.root.as_posix(), **overrides)
        return subprocess.run(
            [
                _BASH,
                self.wrapper.as_posix(),
                (_ROOT / "scripts/cluster/fetch_human_alphafill_bulk.sh").as_posix(),
                source.as_posix(),
                (self.root / "out").as_posix(),
                "--dry-run",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_exact_paths_deduplicate_crlf_and_unterminated_input(self):
        result = self.run_script("P07203\r\nO00116\nP07203")
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = (self.root / "manifest.0").read_text().splitlines()
        self.assertEqual(len(paths), 25)
        self.assertEqual(paths, sorted(set(paths)))
        self.assertIn("O0/AF-O00116-F1-filled_v4.cif.gz", paths)
        self.assertIn("P0/AF-P07203-F1-filled_v6.cif.json", paths)
        self.assertIn("LICENSE.txt", paths)
        args = (self.root / "args.0").read_text().splitlines()
        self.assertIn("--ignore-missing-args", args)
        self.assertIn("--dry-run", args)
        self.assertFalse(any("*" in path for path in paths))
        self.assertNotIn("--recursive", args)

    def test_batches_bound_the_requested_file_list(self):
        result = self.run_script("\n".join(f"P{i:05d}" for i in range(501)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.root.glob("manifest.*"))), 2)
        self.assertEqual(len((self.root / "manifest.0").read_text().splitlines()), 6001)
        self.assertEqual(len((self.root / "manifest.1").read_text().splitlines()), 12)
        self.assertIn("all 2 batches completed", result.stdout)

    def test_rsync_failure_stops_before_next_batch(self):
        result = self.run_script("\n".join(f"P{i:05d}" for i in range(501)), MOCK_RSYNC_EXIT="30")
        self.assertEqual(result.returncode, 30)
        self.assertEqual(len(list(self.root.glob("manifest.*"))), 1)
        self.assertNotIn("completed", result.stdout)

    def test_invalid_input_is_rejected_before_any_rsync_call(self):
        for text in ("", "P07203\n../bad"):
            with self.subTest(text=text):
                result = self.run_script(text)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(list(self.root.glob("args.*")), [])

    def test_version_override_restricts_candidates(self):
        result = self.run_script("O00116", TPW_ALPHAFILL_VERSIONS="4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "manifest.0").read_text().splitlines(),
            [
                "LICENSE.txt",
                "O0/AF-O00116-F1-filled_v4.cif.gz",
                "O0/AF-O00116-F1-filled_v4.cif.json",
            ],
        )

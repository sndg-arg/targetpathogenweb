"""Runs load_score_values for an "Add my own data" upload and turns its
stderr into messages a user can act on.

load_score_values reports every problem on stderr (and only some of them as
a non-zero exit -- a bad column or unknown accession is just skipped), so
the upload view used to print the result to the server log and redirect as
if everything had worked.
"""

import re
import subprocess
import sys
from dataclasses import dataclass, field

MAX_LISTED_ACCESSIONS = 5

_NOT_FOUND_RE = re.compile(r"^'(?P<accession>.*)' was not found$")
_DONE_RE = re.compile(r"done adding properties \((?P<columns>.*)\) to ")


@dataclass
class CustomParamImportResult:
    ok: bool
    loaded_columns: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def _assertion_message(lines):
    for line in reversed(lines):
        if line.startswith(("AssertionError", "CommandError", "ValueError", "KeyError")):
            return line.split(":", 1)[-1].strip() or line
    return ""


def summarize_import_output(returncode, stderr):
    """Pure parser for load_score_values' stderr, split out for testing."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]

    loaded_columns = []
    not_found = []
    problems = []
    for line in lines:
        done = _DONE_RE.search(line)
        if done:
            loaded_columns = [c for c in done.group("columns").split(",") if c]
            continue
        missing = _NOT_FOUND_RE.match(line)
        if missing:
            not_found.append(missing.group("accession"))
            continue
        if line.startswith("Column ") and "invalid" in line:
            problems.append(line)
        elif "has loaded values" in line:
            column = line.split("'")[1] if line.count("'") >= 2 else line
            problems.append(
                f'Column "{column}" already has values for this genome and was skipped. '
                "Upload the same file again and choose Replace to overwrite it."
            )
        elif "does not exists" in line:
            problems.append("This genome could not be found.")

    if not_found:
        unique_missing = sorted(set(not_found))
        listed = ", ".join(unique_missing[:MAX_LISTED_ACCESSIONS])
        more = len(unique_missing) - MAX_LISTED_ACCESSIONS
        suffix = f" and {more} more" if more > 0 else ""
        problems.append(
            f"{len(unique_missing)} accession(s) in the gene column don't match any protein "
            f"of this genome and were ignored: {listed}{suffix}."
        )

    if returncode != 0:
        reason = _assertion_message(lines)
        if "'gene' is not in the column list" in reason:
            reason = "The first column header must be exactly gene."
        elif "no valid score parameters" in reason:
            reason = "No column could be loaded."
        problems.insert(0, reason or "The file could not be processed.")
        return CustomParamImportResult(ok=False, loaded_columns=[], problems=problems)

    return CustomParamImportResult(
        ok=bool(loaded_columns), loaded_columns=loaded_columns, problems=problems
    )


def run_custom_param_import(custom_param, overwrite=False):
    command = [
        sys.executable,
        "./manage.py",
        "load_score_values",
        custom_param.accession,
        custom_param.tsv.path,
        "--datadir",
        "./data",
        "--username",
        custom_param.owner.username,
    ]
    # The form accepts .csv too, but load_score_values defaults to tab --
    # a comma-separated file would otherwise parse as one single column.
    if custom_param.tsv.path.lower().endswith(".csv"):
        command += ["--separator", ","]
    # Without this, "Replace existing file" silently kept the old values:
    # load_score_values skips any column that already has values unless told
    # to overwrite.
    if overwrite:
        command.append("--overwrite")
    completed = subprocess.run(command, capture_output=True, text=True)
    return summarize_import_output(completed.returncode, completed.stderr)

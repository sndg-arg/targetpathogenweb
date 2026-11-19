"""Stage immutable, versioned AlphaFill files without partial final files."""

from pathlib import Path, PurePosixPath
import re

MODEL_NAME = re.compile(r"AF-([A-Z0-9]+)-F1-filled_v(\d+)\.cif\.gz")

# Runs with stdlib Python on the login node; no Django or Biopython needed.
REMOTE_INVENTORY = r"""
import json, re, sys
from pathlib import Path
root = Path(sys.argv[1])
if not root.is_dir():
    raise RuntimeError("AlphaFill directory does not exist: " + str(root))
pattern = re.compile(r"AF-([A-Z0-9]+)-F1-filled_v(\d+)\.cif\.gz")
latest = {}
for folder in [root, *(p for p in root.iterdir() if p.is_dir())]:
    for path in folder.iterdir():
        match = pattern.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        accession, version = match.group(1), int(match.group(2))
        if accession not in latest or version > latest[accession][0]:
            latest[accession] = (version, path)
rows = []
for accession, (_, path) in sorted(latest.items()):
    metadata = path.with_suffix(".json")
    rows.append([accession, path.relative_to(root).as_posix(), path.stat().st_size,
                 metadata.stat().st_size if metadata.is_file() else None])
print(json.dumps({"models": rows, "license_size": (root / "LICENSE.txt").stat().st_size}))
"""


def validate_model_path(accession, relative_path):
    path = PurePosixPath(relative_path)
    match = MODEL_NAME.fullmatch(path.name)
    if (
        not match
        or match.group(1) != accession
        or str(path) != relative_path
        or len(path.parts) not in (1, 2)
        or (len(path.parts) == 2 and path.parts[0] != accession[:2])
    ):
        raise ValueError(f"Invalid AlphaFill model path: {relative_path}")
    return path


def stage_file(sftp, remote_path, local_path, expected_size):
    """Return True if downloaded, False if already staged with the same size."""
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise ValueError(f"Invalid source size for {remote_path}: {expected_size}")
    destination = Path(local_path)
    if destination.is_file() and destination.stat().st_size == expected_size:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    sftp.get(remote_path, str(partial))
    if partial.stat().st_size != expected_size:
        raise ValueError(f"Incomplete transfer: {remote_path}")
    partial.replace(destination)
    return True

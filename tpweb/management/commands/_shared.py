"""Small file-I/O helpers shared across management commands that don't fit
the request/response-oriented tpweb/services layer (no view ever needs
them). The leading underscore keeps Django's command auto-discovery
(`pkgutil.iter_modules`, which already skips `_`-prefixed names) from
treating this as a runnable command.
"""

import csv
import gzip
import os

from django.core.management.base import CommandError


def mkdir(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


def read_manifest(path):
    if not os.path.exists(path):
        raise CommandError(f"Manifest not found: {path}")
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_fasta(faa_gz_path):
    """Read gzipped FASTA, return {locus_tag: sequence}."""
    sequences = {}
    current_tag = None
    current_seq = []

    with gzip.open(faa_gz_path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if current_tag and current_seq:
                    sequences[current_tag] = "".join(current_seq)
                current_tag = line[1:].split()[0]
                current_seq = []
            else:
                current_seq.append(line)

    if current_tag and current_seq:
        sequences[current_tag] = "".join(current_seq)

    return sequences

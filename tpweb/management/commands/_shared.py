"""Small file-I/O and manifest/TSV value-normalization helpers shared across
management commands that don't fit the request/response-oriented
tpweb/services layer (no view ever needs them). The leading underscore keeps
Django's command auto-discovery (`pkgutil.iter_modules`, which already skips
`_`-prefixed names) from treating this as a runnable command.
"""

import ast
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


def clean(value):
    """Normalize a raw manifest/TSV cell: strip whitespace, collapse the
    usual missing-value spellings (None, "nan", "none", "null") to "".
    """
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def as_bool(value):
    return clean(value).lower() in {"1", "true", "yes", "y"}


def structure_code(accession):
    return f"AF_{clean(accession).upper()}"


def norm_source(value):
    value = clean(value).upper()
    for prefix in ("AF_", "CB_"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def is_pdb_code(value, *, require_leading_digit=False):
    value = clean(value).upper()
    if len(value) != 4 or not value.isalnum():
        return False
    if require_leading_digit and not value[0].isdigit():
        return False
    return True


def is_alphafold_uniprot_source(value):
    value = clean(value).upper()
    if not value or is_pdb_code(value) or value.startswith("CB_"):
        return False
    if value.startswith("AF_") or value.startswith("A0A"):
        return True
    if len(value) == 6 and value[0].isalpha() and value[1].isdigit() and value[-1].isdigit():
        return True
    return False


def is_expected_no_pockets(method, pocket):
    return method.lower() == "p2rank" and clean(pocket).lower() == "no_pockets"


def parse_structure_candidates(value, *, dedupe_and_sort=False, require_leading_digit=False):
    value = clean(value)
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = value.replace("{", "").replace("}", "").split(",")
    candidates = (
        clean(candidate).strip("'\"").upper()
        for candidate in parsed
        if is_pdb_code(candidate, require_leading_digit=require_leading_digit)
    )
    return sorted(set(candidates)) if dedupe_and_sort else list(candidates)

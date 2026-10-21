"""Validate original per-protein microbiome genome counts, without imputing zeros."""

import csv
from decimal import Decimal, InvalidOperation


def read_counts(handle, known_loci=None):
    reader = csv.DictReader(handle, delimiter="\t")
    columns = reader.fieldnames or []
    if "gene" not in columns or len(set(columns)) != len(columns):
        raise ValueError("Expected a unique gene column in microbiome counts TSV.")
    candidates = [name for name in columns if name != "gene"]
    if "gut_microbiome_offtarget_counts" in columns:
        column = "gut_microbiome_offtarget_counts"
    elif len(candidates) == 1:
        column = candidates[0]
    else:
        raise ValueError("Ambiguous microbiome count column; inspect the original TSV.")
    counts = {}
    for number, row in enumerate(reader, 2):
        gene = str(row.get("gene") or "").strip()
        if not gene or known_loci is not None and gene not in known_loci:
            raise ValueError(f"Unknown or empty locus at row {number}: {gene}")
        try:
            count = Decimal(str(row.get(column) or "").strip())
            if not count.is_finite() or count < 0 or count != count.to_integral_value():
                raise ValueError
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid nonnegative genome count at row {number}: {gene}") from exc
        value = int(count)
        if gene in counts and counts[gene] != value:
            raise ValueError(f"Conflicting counts for {gene}; no values imported.")
        counts[gene] = value
    return counts

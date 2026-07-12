"""Shared pocket-geometry helpers.

Used by both the 3D viewer (StructureView.py, per-request, one structure at a
time) and the genome-wide pocket-size-outlier indexer (offline management
command) so the outlier definition never drifts between the two.
"""
from __future__ import annotations

import statistics

# Iglewicz-Hoaglin modified z-score convention.
_MAD_CONSTANT = 0.6745
DEFAULT_Z_THRESHOLD = 3.5
MIN_POPULATION = 4


def volume_outlier_map(pdbresidueset_volumes, z_threshold=DEFAULT_Z_THRESHOLD, min_population=MIN_POPULATION):
    """Flag pockets whose volume is unusually large relative to sibling pockets.

    `pdbresidueset_volumes` is an iterable of (pdbresidueset_id, volume) pairs
    for every FPocket pocket of a single structure. Returns
    {pdbresidueset_id: (is_outlier, median, mad)}. Only pockets *larger* than
    the median are ever flagged -- an unusually small pocket isn't the
    failure mode this guards against (a diffuse, low-confidence model region
    reads as an oversized pocket, not an undersized one).

    Comparing against a fixed population size below `min_population`, or a
    population with zero spread (`mad == 0`), can't meaningfully distinguish
    "outlier" from "normal" -- both return `is_outlier=False` for every pocket.
    """
    pairs = [(pid, v) for pid, v in pdbresidueset_volumes if v is not None]
    if len(pairs) < min_population:
        return {pid: (False, None, None) for pid, _ in pairs}

    values = [v for _, v in pairs]
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)

    result = {}
    for pid, v in pairs:
        if mad == 0:
            result[pid] = (False, median, mad)
            continue
        z = _MAD_CONSTANT * (v - median) / mad
        result[pid] = (v > median and z > z_threshold, median, mad)
    return result

"""Cross-predictor (FPocket vs P2Rank) "same binding site" detection.

Shared by tpweb/services/structure_summary.py's render-time pocket cards
(the "Likely same site as X" callout, evaluated only for the top-N pockets
actually displayed) and the index_pocket_consensus management command (which
persists a queryable/rankable ScoreParamValue by checking every pocket, not
just the ones shown on the page).
"""

import math

# Two pocket-core centers within this range are treated as predicting the same
# binding site, regardless of method (FPocket alpha-sphere cloud vs P2Rank residue cloud).
POCKET_CONSENSUS_DISTANCE = 8.0


def center_distance(a, b):
    if a is None or b is None:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def nearest_named_center(center, named_centers):
    """named_centers: [(label, center), ...]. Returns (label, distance) for the closest, or None."""
    best = None
    for label, other in named_centers:
        distance = center_distance(center, other)
        if distance is None:
            continue
        if best is None or distance < best[1]:
            best = (label, distance)
    return best


def residue_identity(residue):
    """Stable residue identity for cross-method pocket comparisons."""
    return (
        str(getattr(residue, "chain", "") or "").strip(),
        int(residue.resid),
        str(getattr(residue, "icode", "") or "").strip(),
    )


def pocket_residue_overlap(left_residues, right_residues):
    """Return overlap metrics without conflating equal numbers across chains."""
    left = {residue_identity(residue) for residue in left_residues}
    right = {residue_identity(residue) for residue in right_residues}
    shared = left & right
    union = left | right
    smaller = min(len(left), len(right))
    return {
        "shared_count": len(shared),
        "smaller_coverage": (len(shared) / smaller * 100.0) if smaller else 0.0,
        "jaccard": (len(shared) / len(union) * 100.0) if union else 0.0,
    }

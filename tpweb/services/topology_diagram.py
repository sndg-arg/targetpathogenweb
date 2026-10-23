"""Membrane topology as a drawing: the chain crossing a membrane once per
transmembrane segment, loops on their side, N and C termini labelled.

Pure geometry over topology segments ({start, end, kind}, kind = membrane /
inside / outside), shared by the pathogen page (Phobius / TMHMM) and the
human page (UniProt). The template only places what this returns.
"""

from __future__ import annotations

import math

WIDTH = 560
MEMBRANE_TOP = 96
MEMBRANE_BOTTOM = 134
HELIX_WIDTH = 14
TAIL = 34
HEIGHT = 230
DOMAIN_MIN = 40


def _merged_helices(segments):
    """Transmembrane segments in order, overlaps merged (two predictors can
    report the same helix)."""
    helices = []
    for seg in sorted(
        (s for s in segments or [] if s.get("kind") == "membrane"), key=lambda s: s["start"]
    ):
        if helices and seg["start"] <= helices[-1]["end"]:
            helices[-1]["end"] = max(helices[-1]["end"], seg["end"])
        else:
            helices.append({"start": seg["start"], "end": seg["end"]})
    return helices


def _n_terminal_side(segments, first_helix):
    """Side of the N terminus: the reported domain before the first helix,
    else the opposite of the one right after it, else inside (most common)."""
    sided = [s for s in segments or [] if s.get("kind") in ("inside", "outside")]
    before = [s for s in sided if s["end"] < first_helix["start"]]
    if before:
        return before[-1]["kind"]
    after = [s for s in sided if s["start"] > first_helix["end"]]
    if after:
        return "inside" if after[0]["kind"] == "outside" else "outside"
    return "inside"


def build_topology_diagram(segments, length, outside_label, inside_label):
    helices = _merged_helices(segments)
    if not helices:
        return None
    side = _n_terminal_side(segments, helices[0])
    n_side = side
    step = (WIDTH - 2 * TAIL - 40) / len(helices)
    x0 = TAIL + 20 + step / 2

    def edge(s):
        return MEMBRANE_TOP if s == "outside" else MEMBRANE_BOTTOM

    def bulge(s, residues):
        # Longer loops reach further from the membrane (log scale, capped).
        height = 14 + min(52, 9 * math.log2(max(residues, 1) + 1))
        return -height if s == "outside" else height

    first_x = x0
    n_start = (first_x - TAIL, edge(side) + bulge(side, 6) * 0.6)
    path = [
        f"M{n_start[0]:.1f} {n_start[1]:.1f}",
        f"Q{first_x - TAIL / 3:.1f} {edge(side):.1f} {first_x:.1f} {edge(side):.1f}",
    ]
    drawn = []
    for i, helix in enumerate(helices):
        x = x0 + i * step
        top_in = side == "outside"
        path.append(f"L{x:.1f} {edge('inside' if top_in else 'outside'):.1f}")
        side = "inside" if top_in else "outside"
        drawn.append(
            {
                "x": round(x - HELIX_WIDTH / 2, 1),
                "y": MEMBRANE_TOP - 6,
                "w": HELIX_WIDTH,
                "h": MEMBRANE_BOTTOM - MEMBRANE_TOP + 12,
                "title": f"TM {i + 1} · {helix['start']}–{helix['end']}",
            }
        )
        if i + 1 < len(helices):
            nx = x0 + (i + 1) * step
            residues = helices[i + 1]["start"] - helix["end"] - 1
            y = edge(side)
            peak = y + bulge(side, residues)
            path.append(f"C{x:.1f} {peak:.1f} {nx:.1f} {peak:.1f} {nx:.1f} {y:.1f}")
    last_x = x0 + (len(helices) - 1) * step
    c_end = (last_x + TAIL, edge(side) + bulge(side, 6) * 0.6)
    path.append(f"Q{last_x + TAIL / 3:.1f} {edge(side):.1f} {c_end[0]:.1f} {c_end[1]:.1f}")
    total = int(length or 0)
    n_domain = _terminal_domain(n_start, n_side, helices[0]["start"] - 1, "N-terminal")
    c_domain = _terminal_domain(
        c_end, side, (total - helices[-1]["end"]) if total else 0, "C-terminal"
    )
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "membrane_y": MEMBRANE_TOP,
        "membrane_h": MEMBRANE_BOTTOM - MEMBRANE_TOP,
        "path": " ".join(path),
        "helices": drawn,
        "count": len(helices),
        "n": _terminus_label(n_start, n_side, n_domain),
        "c": _terminus_label(c_end, side, c_domain),
        "n_domain": n_domain,
        "c_domain": c_domain,
        "n_side": n_side,
        "c_side": side,
        "outside_label": outside_label,
        "inside_label": inside_label,
        "length": length,
    }


def _terminal_domain(end, side, residues, label):
    """A long terminal region (an ectodomain, a cytoplasmic kinase...) drawn
    as a soft domain blob at the end of its tail, sized by residue count."""
    if residues < DOMAIN_MIN:
        return None
    rx = min(66, 16 + 7 * math.log2(residues))
    ry = rx * 0.5
    sign = -1 if side == "outside" else 1
    cx = min(max(end[0], rx + 2), WIDTH - rx - 2)
    cy = end[1] + sign * (ry - 4)
    cy = min(max(cy, ry + 22), HEIGHT - ry - 22)
    return {
        "cx": round(cx, 1),
        "cy": round(cy, 1),
        "rx": round(rx, 1),
        "ry": round(ry, 1),
        "title": f"{label} region · {residues} aa",
        "residues": residues,
    }


def _terminus_label(end, side, domain):
    if domain:
        return {"x": domain["cx"], "y": round(domain["cy"] - 1, 1)}
    return {"x": round(end[0], 1), "y": round(end[1] + (-8 if side == "outside" else 16), 1)}

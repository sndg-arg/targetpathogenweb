"""Protein architecture map for the pathogen protein page, from the InterPro
signature matches already loaded as sequence features, plus experimental
structure coverage. Same shape as the human page's map (see
human_target/services/human_protein_summary.build_human_architecture), so both
pages render it with the shared components/protein/architecture_map.html.
"""

from __future__ import annotations

# One member database draws the domain blocks, in this order of preference;
# the rest stay in the feature table.
_DOMAIN_DBS = (
    "Pfam",
    "SMART",
    "CDD",
    "ProSiteProfiles",
    "NCBIfam",
    "Hamap",
    "Gene3D",
    "SUPERFAMILY",
)
_SIGNAL_PREFIX = "SignalP"
_DISORDER_DBS = {"MobiDBLite"}
_COIL_DBS = {"Coils"}
_TOPOLOGY_DBS = {"Phobius", "TMHMM", "DeepTMHMM"}
COVERAGE_BINS = 120


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ruler(length):
    for step in (10, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        if length / step <= 10:
            break
    return [
        {"position": position, "left": round(position / length * 100, 3)}
        for position in range(step, length, step)
    ]


def _placed(start, end, length, **extra):
    start, end = _int(start), _int(end)
    if start is None:
        return None
    start = max(1, start)
    end = max(start, min(end if end is not None else start, length))
    return {
        "start": start,
        "end": end,
        "left": round((start - 1) / length * 100, 3),
        "width": round((end - start + 1) / length * 100, 3),
        **extra,
    }


def _topology_kind(name):
    text = (name or "").upper()
    if "NON_CYTOPLASMIC" in text:
        return "outside"
    if "CYTOPLASMIC" in text:
        return "inside"
    if "TRANSMEMBRANE" in text or "TMHELIX" in text:
        return "membrane"
    return ""


def build_interpro_architecture(features, length):
    """features: [{start, end, db, term, name}] as serialized on the protein page."""
    length = _int(length)
    if not length or not features:
        return None
    by_db = {}
    for feature in features:
        by_db.setdefault(feature.get("db") or "", []).append(feature)
    domain_db = next((db for db in _DOMAIN_DBS if by_db.get(db)), None)

    topology, signal, domains, disorder, coils, others = [], [], [], [], [], []
    for db, items in by_db.items():
        for feature in items:
            label = feature.get("name") or feature.get("term") or db
            placed = _placed(
                feature.get("start"),
                feature.get("end"),
                length,
                description=label,
                label=f"{db} {feature.get('term') or ''}".strip(),
            )
            if placed is None:
                continue
            if db.startswith(_SIGNAL_PREFIX) or (
                db in _TOPOLOGY_DBS and "SIGNAL" in (feature.get("term") or "").upper()
            ):
                signal.append(placed)
            elif db in _TOPOLOGY_DBS:
                kind = _topology_kind(feature.get("term") or feature.get("name"))
                if kind:
                    topology.append({**placed, "kind": kind})
            elif db == domain_db:
                domains.append(placed)
            elif db in _DISORDER_DBS:
                disorder.append(placed)
            elif db in _COIL_DBS:
                coils.append(placed)
            else:
                others.append(placed)
    if not any((topology, signal, domains, disorder, coils, others)):
        return None
    segment_rows = [
        {"key": key, "label": label, "items": items, "kind": "segments"}
        # Other member-database signatures mostly restate the domains and drew
        # as one solid bar; they stay in the feature table.
        for key, label, items in (
            ("disorder", "Disordered", disorder),
            ("coils", "Coiled coils", coils),
        )
        if items
    ]
    return {
        "length": length,
        "topology": sorted(topology, key=lambda t: t["start"]),
        "signal": signal,
        "domains": sorted(domains, key=lambda d: d["start"]),
        "domain_source": domain_db or "",
        "tick_rows": segment_rows,
        "ruler": ruler(length),
        "has_topology": bool(topology),
    }


def coverage_cells(ranges, length, bins=COVERAGE_BINS):
    """How many structures cover each stretch, from (start, end) ranges."""
    length = _int(length)
    ranges = [(int(s), int(e)) for s, e in ranges if _int(s) and _int(e)]
    if not length or not ranges:
        return None
    bins = max(1, min(bins, length))
    size = length / bins
    depth = [0] * bins
    for start, end in ranges:
        first, last = max(1, start), min(length, end)
        if last < first:
            continue
        for index in range(int((first - 1) // size), int((last - 1) // size) + 1):
            depth[min(index, bins - 1)] += 1
    peak = max(depth)
    if not peak:
        return None
    cells = []
    for index, count in enumerate(depth):
        first = int(index * size) + 1
        cells.append(
            {
                "left": round(index / bins * 100, 3),
                "width": round(100 / bins, 3),
                "count": count,
                "level": 0 if not count else 1 + round(3 * count / peak),
                "first": first,
                "last": max(first, int((index + 1) * size)),
            }
        )
    return {"cells": cells, "structures": len(ranges), "peak": peak}


def format_sequence(sequence, line=60, block=10):
    """UniProt-style layout: lines of 60 residues in blocks of 10."""
    sequence = (sequence or "").strip()
    return [
        {
            "start": line_start + 1,
            "blocks": [
                {
                    "start": line_start + offset + 1,
                    "text": sequence[line_start + offset : line_start + offset + block],
                }
                for offset in range(0, min(line, len(sequence) - line_start), block)
            ],
        }
        for line_start in range(0, len(sequence), line)
    ]

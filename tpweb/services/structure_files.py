import os
import re

from django.conf import settings

from bioseq.io.SeqStore import SeqStore


def structure_file_path(genome_name, protein_accession, structure_code):
    last_path = None
    for base_dir in _candidate_seqstore_dirs():
        seqstore = SeqStore(base_dir)
        candidate = seqstore.structure(genome_name, protein_accession, structure_code)
        last_path = candidate
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(last_path or structure_code)


def _candidate_seqstore_dirs():
    seqs_data_dir = str(getattr(settings, "SEQS_DATA_DIR", "") or "").strip()
    media_root = str(getattr(settings, "MEDIA_ROOT", "") or "").strip()

    candidates = []
    for path in (seqs_data_dir, media_root):
        normalized = os.path.abspath(path) if path else ""
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if seqs_data_dir:
        seqs_dir = os.path.abspath(seqs_data_dir)
        if os.path.basename(seqs_dir) == "seqs":
            parent_dir = os.path.dirname(seqs_dir)
            if parent_dir and parent_dir not in candidates:
                candidates.append(parent_dir)

    return candidates

def detect_structure_format(structure_path):
    """Return the NGL file extension for a stored structure file.

    SeqStore stores every source as gzip under a generic path, so the original
    .pdb/.cif extension is not reliable. Detect from the first text chunk.
    """
    opener = None
    if str(structure_path).lower().endswith(".gz"):
        import gzip
        opener = gzip.open
    else:
        opener = open
    try:
        with opener(structure_path, "rt", errors="replace") as handle:
            head = handle.read(8192)
    except TypeError:
        with opener(structure_path, "rt") as handle:
            head = handle.read(8192)
    return detect_structure_format_from_text(head)


def detect_structure_format_from_text(text):
    head = (text or "").lstrip()
    if head.startswith("data_") or "_atom_site." in head[:8192]:
        return "cif"
    return "pdb"


def display_code(code):
    """Strip pipeline suffixes like _chain_A from PDB codes for user-facing display."""
    return re.sub(r'_chain_\w+$', '', str(code or ''), flags=re.IGNORECASE).upper()


_CHAIN_SUFFIX_RE = re.compile(r'_chain_(\w+)$', re.IGNORECASE)


def disambiguate_display_codes(structures):
    """structures is a list of dicts with "code" and "display_code" keys
    (StructureView.py's all_structures) and a "short_method" key. When two
    entries share the same (short_method, display_code) after
    display_code()'s chain-suffix stripping -- e.g. "6E85" and
    "6E85_CHAIN_A" both display as "6E85" -- disambiguate them instead of
    showing an indistinguishable duplicate in the structure picker.
    """
    groups = {}
    for s in structures:
        groups.setdefault((s["short_method"], s["display_code"]), []).append(s)
    for group in groups.values():
        if len(group) < 2:
            continue
        for s in group:
            match = _CHAIN_SUFFIX_RE.search(s["code"])
            s["display_code"] = f"{s['display_code']} (chain {match.group(1).upper()})" if match else s["code"]

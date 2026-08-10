import math
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

    # Some imports save the file under the bare PDB code even though
    # PDB.code carries a "_chain_X" disambiguation suffix (the same crystal
    # structure can be linked to more than one locus, so the suffix exists
    # to tell those DB rows apart, not necessarily to name a separate
    # per-chain file on disk). Fall back to the base code before giving up
    # -- the NGL chain selector already restricts the displayed chain(s)
    # regardless of which file version loads, so this is a safe substitute,
    # not a wrong-structure risk.
    base_code = CHAIN_SUFFIX_RE.sub("", structure_code)
    if base_code != structure_code:
        for base_dir in _candidate_seqstore_dirs():
            seqstore = SeqStore(base_dir)
            candidate = seqstore.structure(genome_name, protein_accession, base_code)
            if os.path.exists(candidate):
                return candidate

    # tpweb.services.experimental_structures.fetch_and_load_experimental_structures
    # (run via the backfill_experimental_structures command) downloads RCSB
    # PDBs straight into <mid>/<genome_name>/experimental/<accession>/<code>.pdb
    # -- plain text, no .gz -- a storage convention SeqStore itself has never
    # known about (it only understands the alphafold/<accession>/<code>.pdb.gz
    # layout the main pipeline writes). Structures backfilled this way loaded
    # fine into the DB but 404'd here ever since. Try both codes, both with
    # and without .gz, since nothing guarantees every file was written by the
    # exact same version of that command.
    for code in (structure_code, base_code):
        for base_dir in _candidate_seqstore_dirs():
            genome_dir = os.path.join(base_dir, _mid_shard(genome_name), genome_name)
            for filename in (f"{code}.pdb", f"{code}.pdb.gz", f"{code}.cif", f"{code}.cif.gz"):
                candidate = os.path.join(genome_dir, "experimental", protein_accession, filename)
                if os.path.exists(candidate):
                    return candidate

    raise FileNotFoundError(last_path or structure_code)


def _mid_shard(name):
    """Same 3-char middle-of-the-name sharding used throughout the pipeline
    (backfill_experimental_structures.py, import_external_results.py, etc.)
    to spread genome directories across the data volume."""
    n = len(name)
    return name[math.floor(n / 2 - 1) : math.floor(n / 2 + 2)]


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


def _structure_opener(structure_path):
    """Most stored structures are gzip (SeqStore's own convention), but the
    experimental-structures backfill fallback above writes plain text -- pick
    the right opener from the extension instead of assuming either one."""
    if str(structure_path).lower().endswith(".gz"):
        import gzip

        return gzip.open
    return open


def read_structure_text(structure_path):
    """Full text content of a stored structure file, transparently handling
    both the gzip (SeqStore) and plain-text (experimental backfill) cases."""
    opener = _structure_opener(structure_path)
    try:
        with opener(structure_path, "rt", errors="replace") as handle:
            return handle.read()
    except TypeError:
        with opener(structure_path, "rt") as handle:
            return handle.read()


def detect_structure_format(structure_path):
    """Return the NGL file extension for a stored structure file.

    SeqStore stores every source as gzip under a generic path, so the original
    .pdb/.cif extension is not reliable. Detect from the first text chunk.
    """
    opener = _structure_opener(structure_path)
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
    return re.sub(r"_chain_\w+$", "", str(code or ""), flags=re.IGNORECASE).upper()


CHAIN_SUFFIX_RE = re.compile(r"_chain_(\w+)$", re.IGNORECASE)


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
            match = CHAIN_SUFFIX_RE.search(s["code"])
            s["display_code"] = (
                f"{s['display_code']} (chain {match.group(1).upper()})" if match else s["code"]
            )

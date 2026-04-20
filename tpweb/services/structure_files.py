import os

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

"""Visible cross-strain members of Sol's sequence identity groups."""

from tpweb.services.shared_sequence_evidence import apply_shared_sequence_evidence


def identical_siblings_for_bioentry(bioentry, user=None):
    apply_shared_sequence_evidence([bioentry], user)
    evidence = getattr(bioentry, "shared_sequence_evidence", None)
    return evidence.siblings if evidence else []

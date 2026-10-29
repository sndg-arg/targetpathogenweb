"""Skip heavy per-protein work already done for an identical curated copy.

A protein whose 100% identical copy in a curated strain (KP13, KPATCC) already
has a structure, pockets or ligand search shows that evidence live on its own
page (tpweb/services/shared_sequence_evidence.py), so recomputing it only costs
cluster time. Metabolism is not affected: it is never shared and never computed
by these stages. Set TPW_REUSE_IDENTICAL_EVIDENCE=0 to compute everything.
"""

import os


def reuse_enabled():
    return os.environ.get("TPW_REUSE_IDENTICAL_EVIDENCE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def reusable_loci(genome, evidence):
    """Locus tags of `genome` to skip for `evidence` (structure, pockets, ligands)."""
    if not reuse_enabled():
        return set()
    from tpweb.services.shared_sequence_evidence import loci_covered_by_curated_copy

    loci = loci_covered_by_curated_copy(genome, evidence)
    if loci:
        print(
            f"Reusing {evidence} of identical curated copies for {len(loci)} proteins "
            f"(TPW_REUSE_IDENTICAL_EVIDENCE=0 recomputes them)."
        )
    return loci

"""Cross-strain 100%%-identical-sequence links (tpweb.models.IdenticalSequence*).

Display-only by design (see models.IdenticalSequence's docstring) -- nothing
is copied between a protein and its identical siblings in other strains.
This module only answers "what else is this sequence also known as, and do
any of those already have a structure loaded" for the protein detail page.
"""

from tpweb.models import IdenticalSequenceMember


def identical_siblings_for_bioentry(bioentry):
    """[{strain_label, locus_tag, protein_accession, bioentry_id, has_structure}, ...]
    for every other member of `bioentry`'s identity group, or [] if it isn't
    in one (either no 100%-identical match was ever recorded, or this
    strain's genome hasn't been backfilled yet -- see
    backfill_identical_sequence_links)."""
    membership = (
        IdenticalSequenceMember.objects.filter(bioentry=bioentry).select_related("group").first()
    )
    if membership is None:
        return []

    siblings = (
        IdenticalSequenceMember.objects.filter(group_id=membership.group_id)
        .exclude(pk=membership.pk)
        .select_related("bioentry")
        .order_by("strain_label", "locus_tag")
    )

    result = []
    for sibling in siblings:
        has_structure = bool(sibling.bioentry_id) and sibling.bioentry.structures.exists()
        result.append(
            {
                "strain_label": sibling.strain_label,
                "locus_tag": sibling.locus_tag,
                "protein_accession": sibling.protein_accession,
                "bioentry_id": sibling.bioentry_id,
                "has_structure": has_structure,
            }
        )
    return result

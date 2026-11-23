"""Which UniProt entries count as "this same protein" when classifying ligand
evidence as direct (same protein) or via homolog.

A protein's own UniProt cross-references (UnipSp/UnipTr), plus those of its
100% identical copies in other strains (Sol's identity table): an identical
sequence is the same UniProt entry, so a strain whose own UniProt mapping is
missing (VA569 at load time) still gets its direct ligands recognised.
"""


def protein_uniprot_map(accessions):
    """{protein_accession: frozenset(uniprot_ids)} for these protein accessions."""
    from bioseq.models.BioentryDbxref import BioentryDbxref
    from tpweb.models import IdenticalSequenceMember

    clean = {str(a).strip() for a in accessions if a and str(a).strip()}
    if not clean:
        return {}

    def own(accs):
        result = {}
        rows = BioentryDbxref.objects.filter(
            bioentry__accession__in=accs, dbxref__dbname__in=["UnipSp", "UnipTr"]
        ).values_list("bioentry__accession", "dbxref__accession")
        for acc, xref in rows:
            if xref:
                result.setdefault(acc, set()).add(xref)
        return result

    result = own(clean)

    memberships = dict(
        IdenticalSequenceMember.objects.filter(bioentry__accession__in=clean).values_list(
            "bioentry__accession", "group_id"
        )
    )
    if memberships:
        peers = IdenticalSequenceMember.objects.filter(
            group_id__in=set(memberships.values()), bioentry__isnull=False
        ).values_list("group_id", "bioentry__accession")
        accs_by_group = {}
        for group_id, acc in peers:
            accs_by_group.setdefault(group_id, set()).add(acc)
        peer_uniprots = own({a for accs in accs_by_group.values() for a in accs})
        for acc, group_id in memberships.items():
            for peer in accs_by_group.get(group_id, ()):
                result.setdefault(acc, set()).update(peer_uniprots.get(peer, ()))

    return {acc: frozenset(ids) for acc, ids in result.items() if ids}

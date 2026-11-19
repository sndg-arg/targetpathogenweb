"""The protein page's Complexes section, from CORUM (see load_human_complexes_bulk)."""

from human_target.models.HumanComplex import HumanComplex
from human_target.models.HumanProtein import HumanProtein


def _canonical(accession):
    return (accession or "").split("-", 1)[0].strip().upper()


def build_human_complex_context(human_protein):
    complexes = list(
        HumanComplex.objects.filter(protein_links__human_protein=human_protein).order_by(
            "name", "corum_id"
        )
    )
    member_accessions = {
        _canonical(subunit.get("accession"))
        for item in complexes
        for subunit in item.subunits or []
    }
    known = set(
        HumanProtein.objects.filter(uniprot_accession__in=member_accessions).values_list(
            "uniprot_accession", flat=True
        )
    )
    own = human_protein.uniprot_accession
    rows = []
    for item in complexes:
        subunits = []
        for subunit in item.subunits or []:
            accession = _canonical(subunit.get("accession"))
            subunits.append(
                {
                    "accession": accession,
                    "label": subunit.get("gene") or accession,
                    "name": subunit.get("name") or "",
                    "is_self": accession == own,
                    "is_known": accession in known and accession != own,
                }
            )
        # This protein first, then the rest as CORUM lists them.
        subunits.sort(key=lambda subunit: not subunit["is_self"])
        rows.append(
            {
                "corum_id": item.corum_id,
                "name": item.name,
                "pmid": item.pmid,
                "cell_line": item.cell_line,
                "methods": item.purification_methods or [],
                "comment": item.comment,
                "disease_comment": item.disease_comment,
                "subunits": subunits,
            }
        )
    return {"complexes": rows, "has_complexes": bool(rows)}

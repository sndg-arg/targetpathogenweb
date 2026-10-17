"""Groups a human protein's loaded structures into the Structure tab's four
sub-tabs: AlphaFold, AlphaFill, PDB X-ray, PDB NMR.

Reuses the same storage (`BioentryStructure`/`PDB`) and raw-file serving
(`StructureRawView`, `/structure_raw/<id>`) the bacteria Structure section
already uses -- both are generic over any `Bioentry`, no genome/pipeline
coupling. `AFILL` (AlphaFill) is a new `PDB.experiment` value introduced by
`import_human_curated_proteins`; bacteria code never scans/assumes only
AF/CF/EX exist, so this doesn't collide with anything there.

Mean pLDDT and the bound/transplanted-ligand list are computed here from the
`Residue`/`Atom` rows `load_af_model` already parses out of the CIF (via
Bio.PDB) at ingest time -- there is no separate CIF-reparsing step to add:
that atom-level data is already in Postgres for every structure loaded
through the existing, unmodified `load_af_model` command.
"""

from django.db.models import Avg
from django.urls import reverse

from tpweb.models.pdb import Atom, Residue

EXPERIMENT_ALPHAFOLD = "AF"
EXPERIMENT_ALPHAFILL = "AFILL"
EXPERIMENT_EXPERIMENTAL = "EX"

_SOURCE_LABELS = {
    EXPERIMENT_ALPHAFOLD: "AlphaFold",
    EXPERIMENT_ALPHAFILL: "AlphaFill",
}

# Biopython hetflag convention baked into Residue.type by load_af_model:
# "R" = standard residue, "W" = water, anything else ("H_<resname>") = a
# true HETATM/ligand residue.
_NON_LIGAND_RESIDUE_TYPES = ("R", "W")


def _structure_url(pdb_id, protein_id):
    return f"{reverse('tpwebapp:structure_raw', args=[pdb_id])}?protein_id={protein_id}"


def _mean_plddt_for_pdb(pdb_id):
    result = Atom.objects.filter(residue__pdb_id=pdb_id, residue__type="R", name="CA").aggregate(
        Avg("bfactor")
    )
    return result["bfactor__avg"]


def _ligand_summary_for_pdb(pdb_id):
    rows = (
        Residue.objects.filter(pdb_id=pdb_id)
        .exclude(type__in=_NON_LIGAND_RESIDUE_TYPES)
        .values("resname", "chain")
        .distinct()
    )
    chains_by_resname = {}
    for row in rows:
        chains_by_resname.setdefault(row["resname"], set()).add(row["chain"])
    return [
        {"comp": resname, "chains": sorted(chains)}
        for resname, chains in sorted(chains_by_resname.items())
    ]


def build_human_structure_context(bioentry):
    links = list(bioentry.structures.select_related("pdb").all())
    xrefs_by_pdb_id = {
        str(xref.pdb_id or "").strip().upper(): xref
        for xref in bioentry.experimental_structure_xrefs.all()
    }

    alphafold = []
    alphafill = []
    xray = []
    nmr = []

    for link in links:
        pdb = link.pdb
        experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
        code = str(getattr(pdb, "code", "") or "").strip().upper()
        entry = {
            "structure_id": pdb.id,
            "code": code,
            "chain": link.chain or "",
            "resolution": link.resolution or pdb.resolution,
            "url": _structure_url(pdb.id, bioentry.bioentry_id),
            "ligands": _ligand_summary_for_pdb(pdb.id),
        }
        if experiment == EXPERIMENT_ALPHAFOLD:
            entry["label"] = _SOURCE_LABELS[EXPERIMENT_ALPHAFOLD]
            entry["mean_plddt"] = _mean_plddt_for_pdb(pdb.id)
            alphafold.append(entry)
        elif experiment == EXPERIMENT_ALPHAFILL:
            entry["label"] = _SOURCE_LABELS[EXPERIMENT_ALPHAFILL]
            alphafill.append(entry)
        elif experiment == EXPERIMENT_EXPERIMENTAL:
            xref = xrefs_by_pdb_id.get(code)
            method = str(getattr(xref, "method", "") or "").upper()
            entry["method"] = getattr(xref, "method", "") or ""
            entry["title"] = code
            if "NMR" in method:
                nmr.append(entry)
            else:
                xray.append(entry)

    sub_tabs = []
    if alphafold:
        sub_tabs.append(
            {
                "key": "alphafold",
                "label": "AlphaFold",
                "count": len(alphafold),
                "entries": alphafold,
            }
        )
    if alphafill:
        sub_tabs.append(
            {
                "key": "alphafill",
                "label": "AlphaFill",
                "count": len(alphafill),
                "entries": alphafill,
            }
        )
    if xray:
        sub_tabs.append(
            {"key": "xray", "label": "PDB · X-ray", "count": len(xray), "entries": xray}
        )
    if nmr:
        sub_tabs.append({"key": "nmr", "label": "PDB · NMR", "count": len(nmr), "entries": nmr})

    return {
        "sub_tabs": sub_tabs,
        "has_structure": bool(sub_tabs),
        "default_tab": sub_tabs[0]["key"] if sub_tabs else "",
    }

"""Aggregate a protein's external database identifiers into one grouped list.

Every source here is already computed elsewhere for other sections of the protein
page (uniprot_accessions in ProteinView.py, experimental_structures' pdb_id,
binders' chembl entries, metabolic_context's per-reaction kegg_url/metacyc_url) --
this module only regroups what's already in context, it never queries the DB itself.
"""
from __future__ import annotations


def build_protein_cross_references(uniprot_accessions, experimental_structures, binders, metabolic_context):
    sequence = [
        {"source": "UniProt", "id": acc, "url": f"https://www.uniprot.org/uniprotkb/{acc}"}
        for acc in (uniprot_accessions or [])
    ]

    structure = []
    seen_pdb_ids = set()
    for entry in (experimental_structures or []):
        pdb_id = entry.get("pdb_id")
        if not pdb_id or pdb_id in seen_pdb_ids:
            continue
        seen_pdb_ids.add(pdb_id)
        structure.append({
            "source": "PDB",
            "id": pdb_id,
            "url": f"https://www.rcsb.org/structure/{pdb_id}",
        })

    chemistry = []
    seen_chembl_ids = set()
    chembl_entries = [
        *((binders or {}).get("chembl_direct") or []),
        *((binders or {}).get("chembl_homolog") or []),
    ]
    for entry in chembl_entries:
        name = entry.get("name")
        url = entry.get("external_url")
        if not name or not url or name in seen_chembl_ids:
            continue
        seen_chembl_ids.add(name)
        chemistry.append({"source": "ChEMBL", "id": name, "url": url})

    pathways = []
    if metabolic_context:
        seen_kegg_ids = set()
        seen_biocyc_ids = set()
        for reaction in metabolic_context.get("reactions") or []:
            kegg_id = reaction.get("kegg_reaction_id")
            if kegg_id and kegg_id not in seen_kegg_ids:
                seen_kegg_ids.add(kegg_id)
                pathways.append({"source": "KEGG", "id": kegg_id, "url": reaction.get("kegg_url")})

            biocyc_id = reaction.get("reaction_id")
            if biocyc_id and biocyc_id not in seen_biocyc_ids:
                seen_biocyc_ids.add(biocyc_id)
                pathways.append({"source": "BioCyc", "id": biocyc_id, "url": reaction.get("metacyc_url")})

    return {
        "sequence": sequence,
        "structure": structure,
        "chemistry": chemistry,
        "pathways": pathways,
    }

"""Diseases tab context for a human protein.

Reads `HumanProtein.disease_comments` (`[{name, acronym, description, mim}]`,
already parsed at ingest time from UniProt's `DISEASE` comments -- see
`import_human_curated_proteins._extract_comments`) and shapes it for
`human_target/templates/human/human_protein.html`. Mirrors the "build one
context dict, delegate the shaping" style of `human_protein_summary.py`.
"""

from __future__ import annotations


def build_human_disease_context(human_protein):
    diseases = human_protein.disease_comments or []
    return {
        "diseases": diseases,
        "has_diseases": bool(diseases),
    }

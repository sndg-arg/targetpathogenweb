"""Pathways tab context for a human protein.

Reads the protein's `HumanProteinPathway` links (each pointing at a shared
`HumanPathway` reference row -- see `import_human_curated_proteins._load_pathways`)
and shapes them for `human_target/templates/human/human_protein.html`. The
KEGG gene/ortholog node-edge graph itself was already parsed once at ingest
time (`HumanPathway.graph_json`), so this module just picks which pathway is
the default tab -- no XML parsing happens here.
"""

from __future__ import annotations


def build_human_pathway_context(human_protein):
    links = list(
        human_protein.pathway_links.select_related("pathway").order_by(
            "pathway__title", "pathway__kegg_id"
        )
    )
    pathways = [
        {
            "kegg_id": link.pathway.kegg_id,
            "title": link.pathway.title,
            "entry_count": link.pathway.entry_count,
            "relation_count": link.pathway.relation_count,
            "graph_json": link.pathway.graph_json,
            "highlighted_node_id": link.highlighted_node_id,
        }
        for link in links
    ]
    return {
        "pathways": pathways,
        "has_pathways": bool(pathways),
        "default_kegg_id": pathways[0]["kegg_id"] if pathways else "",
    }

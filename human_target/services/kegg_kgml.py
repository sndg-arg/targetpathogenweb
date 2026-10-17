"""Pure KGML parsing, shared between the pilot per-protein ingest
(`import_human_curated_proteins.py`, reading local `kegg_kgml/*.kgml` files
from the reference app's own tree) and the full-proteome bulk ingest
(`load_human_pathways_bulk.py`, fetching KGML live from `rest.kegg.jp`).

No DB access here -- takes a path/string, returns plain dicts/lists.
"""

import xml.etree.ElementTree as ET


def parse_kgml_root(root):
    """Parse one already-parsed KGML `<pathway>` root into a pruned
    node/edge graph: gene/ortholog entries only (compound/map entries
    dropped, matching the reference app's own pruning rule), and only nodes
    that participate in at least one relation (isolated nodes dropped)."""
    nodes = {}
    for entry in root.findall("entry"):
        if entry.get("type") not in ("gene", "ortholog"):
            continue
        entry_id = entry.get("id", "")
        if not entry_id:
            continue
        kegg_ids = (entry.get("name", "") or "").split()
        graphics = entry.find("graphics")
        label = ""
        if graphics is not None:
            label = (graphics.get("name", "") or "").split(",")[0].strip()
        nodes[entry_id] = {
            "id": entry_id,
            "label": label or (kegg_ids[0] if kegg_ids else entry_id),
            "kegg_ids": kegg_ids,
        }

    edges = []
    connected_ids = set()
    for relation in root.findall("relation"):
        entry1 = relation.get("entry1", "")
        entry2 = relation.get("entry2", "")
        if entry1 not in nodes or entry2 not in nodes:
            continue
        subtypes = [
            subtype.get("name", "")
            for subtype in relation.findall("subtype")
            if subtype.get("name")
        ]
        edges.append({"source": entry1, "target": entry2, "subtypes": subtypes})
        connected_ids.add(entry1)
        connected_ids.add(entry2)

    return {
        "nodes": [node for node_id, node in nodes.items() if node_id in connected_ids],
        "edges": edges,
    }


def parse_kgml_file(kgml_path):
    """File-path wrapper around `parse_kgml_root`, for the pilot's local
    `kegg_kgml/*.kgml` tree."""
    tree = ET.parse(kgml_path)
    return parse_kgml_root(tree.getroot())

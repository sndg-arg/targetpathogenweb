"""Read-only coverage calculations, independent of Django and the database."""

import csv
import json
from pathlib import Path


def expected_pdb_pairs(rows):
    """Rows are (UniProt accession, cross references); duplicates count once."""
    pairs = set()
    for accession, references in rows:
        for ref in references or []:
            code = (ref.get("id") or "").strip().upper()
            if ref.get("database") == "PDB" and code:
                pairs.add((accession, code))
    return pairs


def compare_pdb_pairs(expected, registered, linked, sample_size=20, deprecated_linked=None):
    """Only expected pairs contribute to coverage; xrefs alone are insufficient."""
    complete = expected & registered & linked
    missing = expected - complete
    deprecated_only = (expected & (deprecated_linked or set())) - linked
    return {
        "expected_pairs": len(expected),
        "registered_expected_pairs": len(expected & registered),
        "linked_expected_pairs": len(expected & linked),
        "complete_pairs": len(complete),
        "complete_percent": round(100 * len(complete) / len(expected), 2) if expected else None,
        "missing_xrefs": len(expected - registered),
        "missing_structure_links": len(expected - linked),
        "xref_without_structure_link": len((expected & registered) - linked),
        "structure_link_without_xref": len((expected & linked) - registered),
        "pending_pairs": len(missing),
        "pending_distinct_pdb": len({code for _, code in missing}),
        "deprecated_only_pairs": len(deprecated_only),
        "deprecated_only_sample": [list(pair) for pair in sorted(deprecated_only)[:sample_size]],
        "without_any_structure_link": len(expected - linked - (deprecated_linked or set())),
        "extra_registered_pairs": len(registered - expected),
        "pending_sample": [list(pair) for pair in sorted(missing)[:sample_size]],
    }


def reference_inventory(root):
    """Inspect the supplied pilot folders without downloading or changing files."""
    root = Path(root)
    records = {}
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        source = folder / f"{folder.name}_full.json"
        if not source.is_file():
            continue
        with source.open(encoding="utf-8") as handle:
            record = json.load(handle)
        table_counts = {}
        for name in ("known_ligands.tsv", "predicted_ligands.tsv"):
            paths = list((folder / "ligq").rglob(name))
            count = 0
            for path in paths:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    count += sum(1 for _ in csv.DictReader(handle, delimiter="\t"))
            table_counts[name] = {"files": len(paths), "rows": count}
        records[folder.name] = {
            "sequence": (record.get("sequence") or {}).get("value", ""),
            "pdb_ids": sorted(
                code
                for _, code in expected_pdb_pairs(
                    [(folder.name, record.get("uniProtKBCrossReferences"))]
                )
            ),
            "structure_files": {
                name: len(list((folder / name).glob("*.cif")))
                for name in ("AlphaFoldDB", "AlphaFill", "PDB-X-Ray", "PDB-NMR")
            },
            "expression_file": (folder / "Bgee-genex-heatmap.tsv").is_file(),
            "pathway_files": len(list((folder / "kegg_kgml").glob("*.kgml"))),
            "reactions_file": (folder / "reactions.json").is_file(),
            "ligand_tables": table_counts,
        }
    return records

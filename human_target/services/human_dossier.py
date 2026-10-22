"""Target-dossier extras for a human protein, read from the full UniProt entry
kept in `HumanProtein.uniprot_raw` (no extra download): known drugs and
pharmacology links, disease variants with their residue change, PDB coverage
along the sequence, citations, keyword categories and a cell-compartment map
for the subcellular-location diagram. Pure functions over that JSON.
"""

from __future__ import annotations

import re

# Disease acronyms in a variant description: "in GIST and MASTSYS; somatic".
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9-]{1,15}\b")
_CHAIN_RANGE = re.compile(r"(\d+)-(\d+)")
COVERAGE_BINS = 120
PUBLICATION_LIMIT = 12


def _xrefs(raw, database):
    return [
        xref
        for xref in (raw or {}).get("uniProtKBCrossReferences", []) or []
        if xref.get("database") == database and xref.get("id")
    ]


def _prop(xref, key):
    for prop in xref.get("properties", []) or []:
        if prop.get("key") == key:
            value = (prop.get("value") or "").strip()
            return "" if value == "-" else value
    return ""


def build_pharmacology(raw):
    """Drugs listed for the target in DrugBank, UniProt's PHARMACEUTICAL note,
    and links to the pharmacology resources that know this target."""
    drugs = []
    seen = set()
    for xref in _xrefs(raw, "DrugBank"):
        name = _prop(xref, "GenericName") or xref["id"]
        if name.lower() not in seen:
            seen.add(name.lower())
            drugs.append({"id": xref["id"], "name": name})
    drugs.sort(key=lambda drug: drug["name"].lower())
    notes = [
        text.get("value", "")
        for comment in (raw or {}).get("comments", []) or []
        if comment.get("commentType") == "PHARMACEUTICAL"
        for text in comment.get("texts", []) or []
        if text.get("value")
    ]
    links = []
    for database, label, url in (
        ("ChEMBL", "ChEMBL", "https://www.ebi.ac.uk/chembl/target_report_card/{}/"),
        (
            "GuidetoPHARMACOLOGY",
            "IUPHAR/BPS Guide to Pharmacology",
            "https://www.guidetopharmacology.org/GRAC/ObjectDisplayForward?objectId={}",
        ),
        ("OpenTargets", "Open Targets", "https://platform.opentargets.org/target/{}"),
        ("DrugCentral", "DrugCentral", "https://drugcentral.org/?q={}"),
        ("BindingDB", "BindingDB", "https://www.bindingdb.org/uniprot/{}"),
    ):
        refs = _xrefs(raw, database)
        if refs:
            links.append({"label": label, "id": refs[0]["id"], "url": url.format(refs[0]["id"])})
    return {
        "drugs": drugs,
        "notes": notes,
        "links": links,
        "has_pharmacology": bool(drugs or notes or links),
    }


def _variant_diseases(description):
    found = []
    for part in description.split(";"):
        part = part.strip()
        if part.startswith("in "):
            for acronym in _ACRONYM.findall(part[3:]):
                if acronym not in found:
                    found.append(acronym)
    return found


def build_variants(raw, length):
    """Natural variants with their residue change (e.g. D816V), the disease
    acronyms they are reported in, and their position on the map."""
    try:
        length = int(length)
    except (TypeError, ValueError):
        return []
    if length <= 0:
        return []
    variants = []
    for feature in (raw or {}).get("features", []) or []:
        if feature.get("type") != "Natural variant":
            continue
        location = feature.get("location", {}) or {}
        start = (location.get("start") or {}).get("value")
        if not isinstance(start, int):
            continue
        change = feature.get("alternativeSequence", {}) or {}
        original = change.get("originalSequence", "")
        alternatives = change.get("alternativeSequences", []) or []
        if not original:
            label = str(start)
        elif alternatives:
            label = f"{original}{start}{'/'.join(alternatives)}"
        else:
            label = f"{original}{start}del"
        description = feature.get("description", "") or ""
        variants.append(
            {
                "start": start,
                "left": round((min(start, length) - 1) / length * 100, 3),
                "label": label,
                "description": description,
                "diseases": _variant_diseases(description),
            }
        )
    return variants


def disease_variant_counts(variants):
    counts = {}
    for variant in variants:
        for acronym in variant["diseases"]:
            counts[acronym] = counts.get(acronym, 0) + 1
    return counts


def build_pdb_coverage(raw, length, bins=COVERAGE_BINS):
    """How many experimental structures cover each stretch of the sequence,
    from the chain ranges UniProt lists for every PDB entry."""
    try:
        length = int(length)
    except (TypeError, ValueError):
        return None
    entries = _xrefs(raw, "PDB")
    if length <= 0 or not entries:
        return None
    bins = max(1, min(bins, length))
    size = length / bins
    depth = [0] * bins
    for xref in entries:
        covered = set()
        for start, end in _CHAIN_RANGE.findall(_prop(xref, "Chains")):
            first = max(1, int(start))
            last = min(length, int(end))
            for index in range(int((first - 1) // size), int((last - 1) // size) + 1):
                covered.add(min(index, bins - 1))
        for index in covered:
            depth[index] += 1
    peak = max(depth)
    if not peak:
        return None
    cells = []
    for index, count in enumerate(depth):
        first = int(index * size) + 1
        last = max(first, int((index + 1) * size))
        cells.append(
            {
                "left": round(index / bins * 100, 3),
                "width": round(100 / bins, 3),
                "count": count,
                "level": 0 if not count else 1 + round(3 * count / peak),
                "first": first,
                "last": last,
            }
        )
    covered = sum(cell["last"] - cell["first"] + 1 for cell in cells if cell["count"])
    return {
        "cells": cells,
        "structures": len(entries),
        "peak": peak,
        "covered_percent": round(min(100.0, covered / length * 100)),
    }


def build_publications(raw, limit=PUBLICATION_LIMIT):
    """Journal citations, newest first: first author, journal, year."""
    publications = []
    for reference in (raw or {}).get("references", []) or []:
        citation = reference.get("citation", {}) or {}
        pubmed = next(
            (
                xref.get("id")
                for xref in citation.get("citationCrossReferences", []) or []
                if xref.get("database") == "PubMed"
            ),
            "",
        )
        if not pubmed:
            continue
        authors = citation.get("authors", []) or []
        year = str(citation.get("publicationDate", "") or "")[:4]
        publications.append(
            {
                "pubmed": pubmed,
                "title": (citation.get("title") or "").rstrip("."),
                "journal": citation.get("journal", ""),
                "year": year,
                "authors": (authors[0] + (" et al." if len(authors) > 1 else ""))
                if authors
                else "",
            }
        )
    publications.sort(key=lambda pub: pub["year"], reverse=True)
    return {"items": publications[:limit], "total": len(publications)}


_KEYWORD_ORDER = [
    "Molecular function",
    "Biological process",
    "Ligand",
    "Cellular component",
    "Disease",
    "PTM",
    "Domain",
    "Coding sequence diversity",
    "Developmental stage",
    "Technical term",
]


def build_keyword_groups(raw):
    groups = {}
    for keyword in (raw or {}).get("keywords", []) or []:
        if keyword.get("name"):
            groups.setdefault(keyword.get("category") or "Other", []).append(keyword["name"])
    order = _KEYWORD_ORDER + sorted(set(groups) - set(_KEYWORD_ORDER))
    return [
        {"category": category, "keywords": groups[category]}
        for category in order
        if category in groups
    ]


# Subcellular-location text -> compartment drawn on the cell diagram.
# Organelles first: "Golgi apparatus membrane" is the Golgi, not the cell membrane.
_COMPARTMENTS = [
    ("nucleus", ("nucleus", "nucleolus", "nucleoplasm", "chromosome")),
    ("mitochondrion", ("mitochondri",)),
    ("er", ("endoplasmic reticulum", "microsome")),
    ("golgi", ("golgi",)),
    ("vesicle", ("lysosome", "endosome", "vesicle", "peroxisome", "granule", "vacuole")),
    ("cytoskeleton", ("cytoskeleton", "centrosome", "cilium", "microtubule", "actin")),
    ("secreted", ("secreted", "extracellular")),
    ("membrane", ("cell membrane", "plasma membrane", "cell surface", "membrane")),
    ("cytoplasm", ("cytoplasm", "cytosol", "perinuclear")),
]


def compartments_for(locations):
    """Diagram compartments lit up by the protein's subcellular locations."""
    found = []
    for location in locations or []:
        text = location.lower()
        for key, needles in _COMPARTMENTS:
            if any(needle in text for needle in needles):
                if key not in found:
                    found.append(key)
                break
    return found


def build_human_dossier(human_protein):
    raw = human_protein.uniprot_raw or {}
    length = human_protein.sequence_length or len(human_protein.sequence or "")
    variants = build_variants(raw, length)
    return {
        "pharmacology": build_pharmacology(raw),
        "variants": variants,
        "disease_variant_counts": disease_variant_counts(variants),
        "pdb_coverage": build_pdb_coverage(raw, length),
        "publications": build_publications(raw),
        "keyword_groups": build_keyword_groups(raw),
        "compartments": compartments_for(human_protein.subcellular_locations),
    }

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


def build_glance(dossier, diseases, structure, binders, expression, pathways):
    """The hero's "target at a glance" tiles: one per kind of evidence that
    exists, each linking to its section. Values are plain numbers so the page
    can count them up."""
    tiles = []
    drugs = len(dossier["pharmacology"]["drugs"])
    if drugs:
        tiles.append(
            {
                "label": "Clinical precedent",
                "value": drugs,
                "note": "DrugBank compound" + ("s" if drugs != 1 else ""),
                "href": "#section-pharmacology",
            }
        )
    disease_list = diseases.get("diseases") or []
    if disease_list:
        variants = sum(dossier["disease_variant_counts"].values())
        tiles.append(
            {
                "label": "Disease links",
                "value": len(disease_list),
                "note": f"{variants} disease variant{'s' if variants != 1 else ''}"
                if variants
                else "UniProt curated",
                "href": "#section-diseases",
            }
        )
    tabs = structure.get("sub_tabs") or []
    if tabs:
        experimental = sum(tab["count"] for tab in tabs if tab["key"] in ("xray", "nmr"))
        tiles.append(
            {
                "label": "3D structures",
                "value": sum(tab["count"] for tab in tabs),
                "note": f"{experimental} experimental" if experimental else "predicted models",
                "href": "#section-structure",
            }
        )
    total = binders.get("total") or 0
    if total:
        direct = (binders.get("summary") or {}).get("direct_count") or 0
        tiles.append(
            {
                "label": "Ligand evidence",
                "value": total,
                "note": f"{direct} on this exact protein",
                "href": "#section-binders",
            }
        )
    if expression.get("has_expression") and expression.get("tau") is not None:
        tiles.append(
            {
                "label": "Expression",
                "value": f"{expression['tau']:.2f}",
                "prefix": "τ ",
                "note": expression["specificity_label"],
                "href": "#section-expression",
            }
        )
    pathway_list = pathways.get("pathways") or []
    if pathway_list:
        tiles.append(
            {
                "label": "Pathways",
                "value": len(pathway_list),
                "note": "KEGG pathway" + ("s" if len(pathway_list) != 1 else ""),
                "href": "#section-pathways",
            }
        )
    return tiles


_SURFACE = {"membrane", "secreted"}


def build_assessment(dossier, diseases, structure, binders, expression):
    """One line per drug-discovery question, read off the evidence on the page:
    tone is strong / moderate / weak. A reading aid, not a score."""
    rows = []

    drugs = dossier["pharmacology"]["drugs"]
    examples = ", ".join(drug["name"] for drug in drugs[:3])
    rows.append(
        {
            "label": "Clinical precedent",
            "tone": "strong" if drugs else "weak",
            "status": "Precedented" if drugs else "None listed",
            "finding": f"{len(drugs)} DrugBank compound{'s' if len(drugs) != 1 else ''}, e.g. {examples}."
            if drugs
            else "No DrugBank compound is linked to this protein.",
            "href": "#section-pharmacology" if drugs else "",
        }
    )

    disease_list = diseases.get("diseases") or []
    variants = sum(dossier["disease_variant_counts"].values())
    acronyms = ", ".join(d.get("acronym") or d.get("name", "") for d in disease_list[:4])
    rows.append(
        {
            "label": "Genetic evidence",
            "tone": "strong" if variants else ("moderate" if disease_list else "weak"),
            "status": "Disease-linked" if disease_list else "None curated",
            "finding": (
                f"{len(disease_list)} disease association{'s' if len(disease_list) != 1 else ''}"
                f" ({acronyms}){f'; {variants} disease variants mapped' if variants else ''}."
            )
            if disease_list
            else "UniProt lists no disease for this protein.",
            "href": "#section-diseases" if disease_list else "",
        }
    )

    tabs = structure.get("sub_tabs") or []
    experimental = sum(tab["count"] for tab in tabs if tab["key"] in ("xray", "nmr"))
    coverage = dossier.get("pdb_coverage")
    plddt = next(
        (
            entry.get("mean_plddt")
            for tab in tabs
            if tab["key"] == "alphafold"
            for entry in tab["entries"]
            if entry.get("mean_plddt")
        ),
        None,
    )
    if experimental:
        finding = f"{experimental} experimental structure{'s' if experimental != 1 else ''}"
        if coverage:
            finding += f" covering ~{coverage['covered_percent']}% of the sequence"
        rows.append(
            {
                "label": "Structure",
                "tone": "strong",
                "status": "Structurally enabled",
                "finding": finding + ".",
                "href": "#section-structure",
            }
        )
    elif tabs:
        rows.append(
            {
                "label": "Structure",
                "tone": "moderate",
                "status": "Predicted only",
                "finding": "AlphaFold model"
                + (f", mean pLDDT {plddt:.0f}" if plddt else "")
                + "; no experimental structure.",
                "href": "#section-structure",
            }
        )
    else:
        rows.append(
            {
                "label": "Structure",
                "tone": "weak",
                "status": "No structure",
                "finding": "No experimental or predicted structure is loaded.",
                "href": "",
            }
        )

    total = binders.get("total") or 0
    summary = binders.get("summary") or {}
    direct = summary.get("direct_count") or 0
    rows.append(
        {
            "label": "Ligandability",
            "tone": "strong" if direct else ("moderate" if total else "weak"),
            "status": "Ligands on this protein"
            if direct
            else ("Via similar proteins" if total else "No ligand evidence"),
            "finding": (
                f"{summary.get('bioactive_count') or 0} measured bioactivities and"
                f" {summary.get('structural_count') or 0} structural ligands;"
                f" {direct} record{'s' if direct != 1 else ''} on this exact protein."
            )
            if total
            else "No co-crystal, ChEMBL or similarity-based ligand is loaded.",
            "href": "#section-binders" if total else "",
        }
    )

    tau = expression.get("tau")
    if expression.get("has_expression") and tau is not None:
        peak = expression.get("peak") or {}
        tissue = peak.get("tissue") or peak.get("cell_type") or "one tissue"
        if tau >= 0.8:
            row = ("strong", "Tissue-restricted", f"Mostly in {tissue} (τ {tau:.2f}).")
        elif tau >= 0.3:
            row = (
                "moderate",
                "Partly selective",
                f"Highest in {tissue}; τ {tau:.2f} across {expression['tissue_count']} tissues.",
            )
        else:
            row = (
                "weak",
                "Broadly expressed",
                f"Clearly expressed in {expression['expressed_count']} of"
                f" {expression['tissue_count']} tissues (τ {tau:.2f}): expect effects"
                " outside the disease tissue.",
            )
        rows.append(
            {
                "label": "Tissue selectivity",
                "tone": row[0],
                "status": row[1],
                "finding": row[2],
                "href": "#section-expression",
            }
        )

    compartments = dossier.get("compartments") or []
    if compartments:
        surface = bool(_SURFACE.intersection(compartments))
        rows.append(
            {
                "label": "Accessibility",
                "tone": "strong" if surface else "moderate",
                "status": "Extracellular access" if surface else "Intracellular",
                "finding": "Cell surface or secreted: reachable by antibodies as well as small molecules."
                if surface
                else "Inside the cell: needs cell-permeable modalities.",
                "href": "#section-biology",
            }
        )
    return rows


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

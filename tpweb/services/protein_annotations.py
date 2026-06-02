import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology


ANNOTATION_KIND_CONFIG = {
    "ec": {
        "dbnames": [Ontology.EC, "ec"],
        "label": "EC Number",
        "root_label": "EC",
        "supports_prefix": True,
    },
    "go": {
        "dbnames": [Ontology.GO, "go"],
        "label": "GO Term",
        "root_label": "GO",
        "supports_prefix": False,
    },
}

EC_HIERARCHY_LABELS_PATH = Path(__file__).resolve().parents[1] / "data" / "ec_hierarchy_labels.json"


@lru_cache(maxsize=1)
def _load_ec_hierarchy_labels():
    with EC_HIERARCHY_LABELS_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    def _clean_dict(section_name):
        return {
            str(key).strip(): str(value).strip()
            for key, value in dict(payload.get(section_name) or {}).items()
            if str(key).strip() and str(value).strip()
        }

    class_labels = _clean_dict("class_labels")
    prefix_labels = {}
    for section in ("subclass_labels", "subsubclass_labels"):
        prefix_labels.update(_clean_dict(section))
    enzyme_names = _clean_dict("enzyme_names")

    return {
        "class_labels": class_labels,
        "prefix_labels": prefix_labels,
        "enzyme_names": enzyme_names,
    }


def ec_enzyme_name(accession):
    """Look up an EC enzyme name from the curated nomenclature JSON."""
    accession = str(accession or "").strip()
    if not accession:
        return ""
    ec_labels = _load_ec_hierarchy_labels()
    return ec_labels["enzyme_names"].get(accession, "")


def normalize_annotation_kind(kind):
    normalized = str(kind or "").strip().lower()
    if normalized in ANNOTATION_KIND_CONFIG:
        return normalized
    return "ec"


def annotation_kind_label(kind):
    config = ANNOTATION_KIND_CONFIG[normalize_annotation_kind(kind)]
    return config["label"]


def annotation_supports_prefix(kind):
    config = ANNOTATION_KIND_CONFIG[normalize_annotation_kind(kind)]
    return config["supports_prefix"]


def _annotation_dbname(kind):
    config = ANNOTATION_KIND_CONFIG[normalize_annotation_kind(kind)]
    dbnames = config["dbnames"]
    return dbnames[0]


def annotation_dbnames(kind):
    return ANNOTATION_KIND_CONFIG[normalize_annotation_kind(kind)]["dbnames"]


def _annotation_name(dbxref_relation):
    dbxref = getattr(dbxref_relation, "dbxref", None)
    if dbxref is None:
        return ""
    terms = getattr(dbxref, "terms", None)
    if terms is None:
        return ""
    try:
        first_term = terms.all()[0]
    except Exception:
        return ""
    return getattr(getattr(first_term, "term", None), "definition", "") or ""


def iter_protein_annotations(protein, kind):
    dbnames = set(annotation_dbnames(kind))
    seen_accessions = set()
    dbxref_manager = getattr(protein, "dbxrefs", None)
    if dbxref_manager is None:
        return
    dbxref_relations = dbxref_manager.all() if hasattr(dbxref_manager, "all") else dbxref_manager

    for dbxref_relation in dbxref_relations:
        dbxref = getattr(dbxref_relation, "dbxref", None)
        accession = str(getattr(dbxref, "accession", "") or "").strip()
        if not accession or accession in seen_accessions:
            continue
        if getattr(dbxref, "dbname", None) not in dbnames:
            continue
        seen_accessions.add(accession)
        yield {
            "accession": accession,
            "name": _annotation_name(dbxref_relation),
        }


def protein_annotation_accessions(protein, kind):
    return [item["accession"] for item in iter_protein_annotations(protein, kind)]


def protein_annotation_badges(protein, kind, limit=3):
    badges = list(iter_protein_annotations(protein, kind))
    return badges[:limit]


def protein_annotation_summary(protein, kind, limit=3):
    """Return badges plus total count for '+N more' display."""
    all_annotations = list(iter_protein_annotations(protein, kind))
    return {
        "badges": all_annotations[:limit],
        "total": len(all_annotations),
        "remaining": max(0, len(all_annotations) - limit),
    }


def protein_annotation_text(protein, kind, limit=3):
    accessions = protein_annotation_accessions(protein, kind)
    if not accessions:
        return "-"
    return ", ".join(accessions[:limit])


def annotation_term_name(kind, accession):
    accession = str(accession or "").strip()
    if not accession:
        return ""

    dbxref = (
        Dbxref.objects.filter(
            dbname__in=annotation_dbnames(kind),
            accession=accession,
        )
        .prefetch_related("terms__term")
        .first()
    )
    if dbxref is None:
        return ""

    terms = getattr(dbxref, "terms", None)
    if terms is None:
        return ""
    try:
        first_term = terms.all()[0]
    except Exception:
        return ""
    return getattr(getattr(first_term, "term", None), "definition", "") or ""


def _ec_resolve_name(accession, exact_names):
    """Resolve an EC name: JSON nomenclature first, DB fallback second."""
    ec_labels = _load_ec_hierarchy_labels()
    parts = accession.split(".")

    if "-" in parts:
        return "partial EC assignment"
    if len(parts) == 1:
        return ec_labels["class_labels"].get(accession, "")
    if len(parts) <= 3:
        return ec_labels["prefix_labels"].get(accession, "")

    # Level 4: curated JSON first, then DB-derived name as fallback
    return (
        ec_labels["enzyme_names"].get(accession)
        or exact_names.get(accession)
        or ""
    )


def _ec_display_label(prefix, exact_names):
    prefix = str(prefix or "").strip()
    if not prefix:
        return ""
    name = _ec_resolve_name(prefix, exact_names)
    return f"{prefix} {name}" if name else prefix


def _ec_hover_label(prefix, exact_names):
    prefix = str(prefix or "").strip()
    if not prefix:
        return ""
    name = _ec_resolve_name(prefix, exact_names)
    return f"{prefix} — {name}" if name else prefix


def build_annotation_explorer(proteins, kind):
    kind = normalize_annotation_kind(kind)
    config = ANNOTATION_KIND_CONFIG[kind]
    root_id = f"{kind}:root"
    root_label = config["root_label"]

    exact_counts = defaultdict(set)
    exact_names = {}
    prefix_counts = defaultdict(set)

    for protein in proteins:
        protein_id = getattr(protein, "bioentry_id", None)
        for annotation in iter_protein_annotations(protein, kind):
            accession = annotation["accession"]
            exact_counts[accession].add(protein_id)
            if annotation["name"]:
                exact_names.setdefault(accession, annotation["name"])

            if kind == "ec":
                parts = accession.split(".")
                prefixes = [".".join(parts[: idx + 1]) for idx in range(len(parts))]
            else:
                prefixes = [accession]

            for prefix in prefixes:
                prefix_counts[prefix].add(protein_id)

    ids = [root_id]
    labels = [root_label]
    parents = [""]
    values = [sum(len(protein_ids) for protein_ids in exact_counts.values()) or 0]
    hover_labels = [root_label]

    if kind == "ec":
        ordered_prefixes = sorted(prefix_counts, key=lambda value: (value.count("."), value))
        for prefix in ordered_prefixes:
            parent_value = prefix.rsplit(".", 1)[0] if "." in prefix else root_id
            parent_id = f"{kind}:{parent_value}" if parent_value != root_id else root_id
            display_label = _ec_display_label(prefix, exact_names)
            hover_label = _ec_hover_label(prefix, exact_names)
            ids.append(f"{kind}:{prefix}")
            labels.append(display_label)
            parents.append(parent_id)
            values.append(len(prefix_counts[prefix]))
            hover_labels.append(hover_label)
    else:
        ordered_accessions = sorted(exact_counts)
        for accession in ordered_accessions:
            display_label = exact_names.get(accession, accession)
            hover_label = accession
            if exact_names.get(accession):
                hover_label = f"{accession} — {exact_names[accession]}"
            ids.append(f"{kind}:{accession}")
            labels.append(display_label)
            parents.append(root_id)
            values.append(len(exact_counts[accession]))
            hover_labels.append(hover_label)

    table_rows = []
    for accession, protein_ids in exact_counts.items():
        table_rows.append(
            {
                "accession": accession,
                "name": exact_names.get(accession, ""),
                "protein_count": len(protein_ids),
            }
        )
    table_rows.sort(key=lambda row: (-row["protein_count"], row["accession"]))

    return {
        "kind": kind,
        "kind_label": config["label"],
        "node_count": len(ids) - 1,
        "annotation_count": len(exact_counts),
        "chart": {
            "ids": ids,
            "labels": labels,
            "parents": parents,
            "values": values,
            "hover_labels": hover_labels,
        },
        "rows": table_rows,
    }

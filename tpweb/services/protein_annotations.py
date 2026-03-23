from collections import defaultdict

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

EC_CLASS_LABELS = {
    "1": "Oxidoreductases",
    "2": "Transferases",
    "3": "Hydrolases",
    "4": "Lyases",
    "5": "Isomerases",
    "6": "Ligases",
    "7": "Translocases",
}

EC_PREFIX_LABELS = {
    "1.1": "Acting on the CH-OH group of donors",
    "1.2": "Acting on the aldehyde or oxo group of donors",
    "1.3": "Acting on the CH-CH group of donors",
    "1.4": "Acting on the CH-NH2 group of donors",
    "1.5": "Acting on the CH-NH group of donors",
    "1.6": "Acting on NADH or NADPH",
    "1.7": "Acting on nitrogenous compounds as donors",
    "1.8": "Acting on sulfur groups of donors",
    "1.9": "Acting on a heme group of donors",
    "1.10": "Acting on diphenols and related substances",
    "1.11": "Acting on peroxides as acceptor",
    "1.12": "Acting on hydrogen as donor",
    "1.13": "Incorporating one atom of oxygen",
    "1.14": "Incorporation of molecular oxygen",
    "1.15": "Acting on superoxide radicals",
    "1.16": "Oxidizing metal ions",
    "1.17": "Acting on CH or CH2 groups",
    "1.18": "Acting on iron-sulfur proteins as donors",
    "1.19": "Acting on reduced flavodoxin as donor",
    "1.20": "Acting on phosphorus or arsenic in donors",
    "1.21": "Acting on X-H and Y-H to form X-Y",
    "1.22": "Acting on halogen in donors",
    "1.23": "Reducing C-O-C group in donors",
    "1.1.1": "With NAD+ or NADP+ as acceptor",
    "1.1.2": "With cytochrome as acceptor",
    "1.1.3": "With oxygen as acceptor",
    "1.1.5": "With a quinone or related compound as acceptor",
    "2.1": "Transferring one-carbon groups",
    "2.2": "Transferring aldehyde or ketonic groups",
    "2.3": "Acyltransferases",
    "2.4": "Glycosyltransferases",
    "2.5": "Transferring alkyl or aryl groups",
    "2.6": "Transferring nitrogenous groups",
    "2.7": "Transferring phosphorus-containing groups",
    "2.7.1": "Phosphotransferases with alcohol group as acceptor",
    "2.7.2": "With a carboxyl group as acceptor",
    "2.7.3": "With a nitrogenous group as acceptor",
    "2.7.4": "With a phosphate group as acceptor",
    "2.7.7": "Nucleotidyltransferases",
    "2.7.11": "Protein-serine/threonine kinases",
    "2.8": "Transferring sulfur-containing groups",
    "2.9": "Transferring selenium-containing groups",
    "2.10": "Transferring molybdenum or tungsten-containing groups",
    "3.1": "Acting on ester bonds",
    "3.2": "Acting on glycosyl compounds",
    "3.3": "Acting on ether bonds",
    "3.4": "Acting on peptide bonds",
    "3.1.3": "Phosphoric monoester hydrolases",
    "3.5": "Acting on carbon-nitrogen bonds",
    "3.5.4": "Acting on cyclic amidines",
    "3.6": "Acting on acid anhydrides",
    "3.7": "Acting on carbon-carbon bonds",
    "3.8": "Acting on halide bonds",
    "3.9": "Acting on phosphorus-nitrogen bonds",
    "3.10": "Acting on sulfur-nitrogen bonds",
    "3.11": "Acting on carbon-phosphorus bonds",
    "3.12": "Acting on sulfur-sulfur bonds",
    "3.13": "Acting on carbon-sulfur bonds",
    "3.6.1": "Phosphorus-containing anhydrides",
    "3.6.3": "Transmembrane movement of substances",
    "4.1": "Carbon-carbon lyases",
    "4.2": "Carbon-oxygen lyases",
    "4.3": "Carbon-nitrogen lyases",
    "4.4": "Carbon-sulfur lyases",
    "4.5": "Carbon-halide lyases",
    "4.6": "Phosphorus-oxygen lyases",
    "4.2.1": "Hydro-lyases",
    "5.1": "Racemases and epimerases",
    "5.2": "Cis-trans isomerases",
    "5.3": "Intramolecular oxidoreductases",
    "5.4": "Intramolecular transferases",
    "5.5": "Intramolecular lyases",
    "5.6": "Macromolecular conformational isomerases",
    "5.4.2": "Phosphotransferases",
    "6.1": "Forming carbon-oxygen bonds",
    "6.2": "Forming carbon-sulfur bonds",
    "6.3": "Forming carbon-nitrogen bonds",
    "6.4": "Forming carbon-carbon bonds",
    "6.5": "Forming phosphoric ester bonds",
    "6.6": "Forming nitrogen-metal bonds",
    "6.3.5": "Using glutamine as amido-N donor",
    "7.1": "Catalyzing transmembrane movement of hydrons",
    "7.2": "Catalyzing transmembrane movement of inorganic cations",
    "7.3": "Catalyzing transmembrane movement of organic or inorganic anions",
    "7.4": "Catalyzing transmembrane movement of amino acids and peptides",
}


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


def _ec_display_label(prefix, exact_names):
    prefix = str(prefix or "").strip()
    if not prefix:
        return ""

    parts = prefix.split(".")
    if len(parts) == 1:
        class_label = EC_CLASS_LABELS.get(prefix)
        if class_label:
            return f"{prefix} {class_label}"
        return prefix

    prefix_label = EC_PREFIX_LABELS.get(prefix)
    if prefix_label:
        return f"{prefix} {prefix_label}"

    if prefix in exact_names and len(parts) >= 4:
        return exact_names[prefix]

    return prefix


def _ec_hover_label(prefix, exact_names):
    prefix = str(prefix or "").strip()
    if not prefix:
        return ""

    if prefix in exact_names:
        return f"{prefix} — {exact_names[prefix]}"

    class_label = EC_CLASS_LABELS.get(prefix)
    if class_label:
        return f"{prefix} — {class_label}"

    prefix_label = EC_PREFIX_LABELS.get(prefix)
    if prefix_label:
        return f"{prefix} — {prefix_label}"

    return prefix


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

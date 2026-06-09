from django.shortcuts import render
from django.http import Http404
from django.views import View
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

import itertools

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.Binders import Binders
from tpweb.models.pdb import PDBResidueSet
from tpweb.models.BioentryStructure import ExperimentalStructureXref
from tpweb.models.ScoreParamValue import ScoreParamValue
from .StructureView import pdb_structure
from tpweb.services.protein_annotations import annotation_dbnames, protein_annotation_badges, iter_protein_annotations
from tpweb.services.csv_exports import xlsx_sections_response
from tpweb.services.pipeline_status import (
    annotate_pipeline_status_for_genome,
    get_pipeline_status,
)
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    user_can_access_genome_name,
)
from tpweb.services.structure_sources import (
    PDB_MODEL_EXPERIMENTS,
    summarize_structure_sources,
    sort_structures_by_preference as _sort_structures_by_preference,
    structure_toggle_label as _structure_toggle_label,
    PDB_MODEL_EXPERIMENTS as _PDB_MODEL_EXPERIMENTS,
)

KNOWN_BINDER_CAP = 100
ZINC_BINDER_CAP = 50
_PAINS_CATALOG = None


def _short_method(method_str):
    """Compact display label for a PDB method string from UniProt."""
    m = (method_str or "").upper()
    if "X-RAY" in m or "DIFFRACTION" in m:
        return "X-ray"
    if "ELECTRON" in m or "MICROSCOPY" in m or "CRYO" in m:
        return "EM"
    if "NMR" in m:
        return "NMR"
    return method_str or "—"


def _structure_toggle_detail(link, protein_length=None):
    """Return (label, detail) for a structure source toggle button.

    For experimental PDB: 'PDB XXXX' + '99% · 1.85 Å'.
    For predicted models: model name + coverage hint.
    """
    pdb = link.pdb
    experiment = (getattr(pdb, "experiment", "") or "").upper()
    start = getattr(link, "uniprot_start", None)
    end = getattr(link, "uniprot_end", None)

    def _coverage_pct():
        if start is not None and end is not None and protein_length:
            return (end - start + 1) / protein_length * 100
        return None

    if experiment == "EX":
        code = (getattr(pdb, "code", "") or "").upper()
        resolution = getattr(link, "resolution", None)
        label = f"PDB {code}" if code else "Crystal structure"
        parts = []
        pct = _coverage_pct()
        if pct is not None:
            parts.append(f"{pct:.0f}%")
        if resolution is not None:
            parts.append(f"{resolution:.2f} Å")
        detail = " · ".join(parts)
        return label, detail

    if experiment == "CF":
        label = "ColabFold model"
    elif experiment == "AF":
        label = "AlphaFold model"
    else:
        label = _structure_toggle_label(experiment)

    pct = _coverage_pct()
    if pct is not None:
        detail = f"{pct:.0f}% coverage"
    elif start is None and end is None:
        detail = "full sequence"
    else:
        detail = ""
    return label, detail


def _druggability_label(value):
    """Return (label, tone) for a numeric FPocket druggability score."""
    if value is None:
        return None
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    label = f"{v:.3f}".rstrip("0").rstrip(".")
    if v >= 0.7:
        return (label, "high")
    elif v >= 0.4:
        return (label, "mid")
    elif v > 0:
        return (label, "low")
    return None


_SCORE_META = [
    # (score_name, display_label, category, good_values, bad_values)
    ("human_offtarget",          "Human off-target",           "off_target",    ["no_hit"], ["hit"]),
    ("human_identity",           "Human identity (%)",         "off_target",    [],         []),
    ("human_evalue",             "Human E-value",              "off_target",    [],         []),
    ("gut_microbiome_offtarget", "Gut microbiome off-target",  "off_target",    ["no_hit"], ["hit"]),
    ("hit_in_deg",               "Essential (DEG)",            "essentiality",  ["Y"],      ["N"]),
    ("deg_identity",             "DEG identity (%)",           "essentiality",  [],         []),
    ("deg_evalue",               "DEG E-value",                "essentiality",  [],         []),
    ("Localization",             "Localization",               "localization",  [], []),
    ("colabfold_plddt",          "ColabFold pLDDT",            "structure",     [],         []),
]

def _build_target_profile(raw_scores):
    items = []
    for name, label, category, good_vals, bad_vals in _SCORE_META:
        val = raw_scores.get(name)
        if not val:
            continue
        if val in good_vals:
            tone = "good"
        elif val in bad_vals:
            tone = "bad"
        else:
            tone = "neutral"
        display = val.replace("_", " ").replace("no hit", "No hit").replace("no_hit", "No hit")
        items.append({"label": label, "value": display, "tone": tone, "category": category})
    return items


def _raw_score(raw_scores, name):
    value = raw_scores.get(name)
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in {"", "nan", "none", "null"}:
        return ""
    return value


def _format_score_value(value):
    value = _raw_score({"value": value}, "value")
    if not value:
        return ""
    try:
        return f"{float(value.replace(',', '.')):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return value


def _structure_source_kind(identifier):
    ident = (identifier or "").strip()
    upper = ident.upper()
    if not ident:
        return ""
    if upper.startswith("CB_"):
        return "ColabFold / curated model"
    if upper.startswith("AF_"):
        return "AlphaFold / UniProt model"
    if len(ident) == 4 and ident.isalnum():
        return "PDB experimental structure"
    if upper.startswith("A0A") or (any(ch.isdigit() for ch in ident) and any(ch.isalpha() for ch in ident)):
        return "AlphaFold / UniProt model"
    return "Curated structure"


def _format_pocket_label(value):
    label = (value or "").strip()
    if not label:
        return ""
    if label == "No_pockets":
        return "No pockets"
    if label.lower().startswith("pocket pocket"):
        suffix = label[len("Pocket pocket"):].strip()
        return f"Pocket {suffix}" if suffix else "Pocket"
    return label

def _build_selected_pocket_evidence(raw_scores):
    fpocket_score = _format_score_value(_raw_score(raw_scores, "Druggability"))
    fpocket_structure = _raw_score(raw_scores, "best_fpocket_structure")
    fpocket_pocket = _format_pocket_label(_raw_score(raw_scores, "fpocket_pocket"))
    p2rank_score = _format_score_value(_raw_score(raw_scores, "p2rank_probability"))
    p2rank_structure = _raw_score(raw_scores, "best_p2rank_structure")
    p2rank_pocket = _format_pocket_label(_raw_score(raw_scores, "p2rank_pocket"))
    colabfold_fpocket_score = _format_score_value(_raw_score(raw_scores, "colabfold_druggability_score"))
    colabfold_fpocket_pocket = _format_pocket_label(_raw_score(raw_scores, "colabfold_fpocket_pocket"))
    colabfold_p2rank_score = _format_score_value(_raw_score(raw_scores, "colabfold_p2rank_probability"))
    colabfold_p2rank_pocket = _format_pocket_label(_raw_score(raw_scores, "colabfold_p2rank_pocket"))

    has_any = any([
        fpocket_score, fpocket_structure, fpocket_pocket,
        p2rank_score, p2rank_structure, p2rank_pocket,
        colabfold_fpocket_score, colabfold_fpocket_pocket,
        colabfold_p2rank_score, colabfold_p2rank_pocket,
    ])
    if not has_any:
        return None

    selected_source_kind = _structure_source_kind(fpocket_structure or p2rank_structure)
    return {
        "selected_source_kind": selected_source_kind,
        "fpocket": {
            "score": fpocket_score,
            "structure": fpocket_structure,
            "pocket": fpocket_pocket,
            "source_kind": _structure_source_kind(fpocket_structure),
        },
        "p2rank": {
            "score": p2rank_score,
            "structure": p2rank_structure,
            "pocket": p2rank_pocket,
            "source_kind": _structure_source_kind(p2rank_structure),
        },
        "colabfold": {
            "fpocket_score": colabfold_fpocket_score,
            "fpocket_pocket": colabfold_fpocket_pocket,
            "p2rank_score": colabfold_p2rank_score,
            "p2rank_pocket": colabfold_p2rank_pocket,
        },
    }


def _truthy_score(value):
    return str(value or "").strip().lower() in {"true", "t", "yes", "y", "1"}


def _build_conservation_profile(raw_scores):
    roary_raw = _raw_score(raw_scores, "core_roary")
    corecruncher_raw = _raw_score(raw_scores, "core_corecruncher")
    if not roary_raw and not corecruncher_raw:
        return None
    roary = _truthy_score(roary_raw)
    corecruncher = _truthy_score(corecruncher_raw)
    return {
        "roary": roary,
        "corecruncher": corecruncher,
        "is_core": roary and corecruncher,
        "roary_label": "core" if roary else "accessory",
        "corecruncher_label": "core" if corecruncher else "accessory",
    }


def _build_microbiome_context(raw_scores):
    count = _format_score_value(_raw_score(raw_scores, "gut_microbiome_offtarget_counts"))
    total = _format_score_value(_raw_score(raw_scores, "gut_microbiome_genomes_analyzed"))
    norm = _format_score_value(_raw_score(raw_scores, "gut_microbiome_offtarget_norm"))
    if not count and not total and not norm:
        return None
    return {"count": count, "total": total, "norm": norm}


def _has_pocket_data(pdb_obj):
    return PDBResidueSet.objects.filter(
        pdb=pdb_obj,
        residue_set__name__in=["FPocketPocket", "P2RankPocket"],
    ).exists()


def _chain_selector(chain):
    chain = (chain or "").strip()
    return f":{chain}" if chain else "polymer"


def _first_location(feature):
    locations = getattr(feature, "locations", None)
    if locations is None:
        return None
    try:
        return locations.all()[0]
    except Exception:
        return None


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


def _format_resolution(value):
    if value is None:
        return "—"
    try:
        v = float(value)
        if v <= 0 or v > 100:
            return "—"
        return f"{v:.2f} Å"
    except (TypeError, ValueError):
        return "—"


def _external_structure_links(pdb_id):
    pdb_id = (pdb_id or "").strip()
    if not pdb_id:
        return {}
    upper_id = pdb_id.upper()
    lower_id = pdb_id.lower()
    return {
        "pdbe": f"https://www.ebi.ac.uk/pdbe/entry/pdb/{lower_id}",
        "rcsb": f"https://www.rcsb.org/structure/{upper_id}",
        "pdbj": f"https://pdbj.org/mine/summary/{upper_id}",
        "pdbsum": f"https://www.ebi.ac.uk/thornton-srv/databases/cgi-bin/pdbsum/GetPage.pl?pdbcode={lower_id}",
        "source": f"https://files.rcsb.org/download/{upper_id}.pdb",
    }


def _coverage_payload(start, end, protein_length):
    if not start or not end or not protein_length:
        return {
            "positions": "—",
            "coverage_label": "—",
            "coverage_left": "0%",
            "coverage_width": "0%",
            "has_positions": False,
        }

    start = int(start)
    end = int(end)
    if end < start:
        start, end = end, start
    start = min(max(1, start), int(protein_length))
    end = min(max(1, end), int(protein_length))

    span = max(0, end - start + 1)
    coverage = min(100.0, max(0.0, (span / protein_length) * 100.0))
    left = min(100.0, max(0.0, ((start - 1) / protein_length) * 100.0))
    width = min(100.0 - left, coverage)
    return {
        "positions": f"{start}-{end}",
        "coverage_label": f"{coverage:.1f}%",
        "coverage_left": f"{left:.3f}%",
        "coverage_width": f"{max(width, 1.0):.3f}%",
        "has_positions": True,
    }


def _experimental_structure_entry(pdb_id, method, resolution, chains, start, end, protein_length, loaded_link=None):
    coverage = _coverage_payload(start, end, protein_length)
    chain_sel = _chain_selector(getattr(loaded_link, "chain", None)) if loaded_link else ""
    return {
        "pdb_id": (pdb_id or "").upper(),
        "method": _short_method(method),
        "resolution": _format_resolution(resolution),
        "chains": chains or "-",
        "links": _external_structure_links(pdb_id),
        "loaded": loaded_link is not None,
        "loaded_structure_id": getattr(getattr(loaded_link, "pdb", None), "id", None),
        "chain_selector": chain_sel,
        **coverage,
    }


def _structure_source_name(experiment):
    experiment = str(experiment or "").strip().upper()
    if experiment == "EX":
        return "PDB"
    return _structure_toggle_label(experiment)


def _viewer_structure_payload(link, protein_length):
    pdb = getattr(link, "pdb", None)
    experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
    source_name = _structure_source_name(experiment)
    code = str(getattr(pdb, "code", "") or "").strip().upper()
    coverage = _coverage_payload(
        getattr(link, "uniprot_start", None),
        getattr(link, "uniprot_end", None),
        protein_length,
    )
    resolution = _format_resolution(getattr(link, "resolution", None) or getattr(pdb, "resolution", None))

    if source_name == "PDB" and code:
        short_label = f"PDB {code}"
    elif code:
        short_label = f"{source_name} {code}"
    else:
        short_label = source_name

    details = []
    if coverage.get("has_positions"):
        details.append(coverage["coverage_label"])
    if resolution != "-":
        details.append(resolution)

    return {
        "short_label": short_label,
        "detail_label": " · ".join(details),
        "source_name": source_name,
        "code": code,
        "positions": coverage["positions"],
        "coverage_label": coverage["coverage_label"],
        "resolution": resolution,
    }


def _build_predicted_structures(links, protein_length, primary_link=None, alt_link=None):
    primary_pdb_id = getattr(getattr(primary_link, "pdb", None), "id", None) if primary_link else None
    alt_pdb_id = getattr(getattr(alt_link, "pdb", None), "id", None) if alt_link else None
    entries = []
    for link in links:
        pdb = link.pdb
        experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
        code = str(getattr(pdb, "code", "") or "").strip().upper()
        if experiment == "CF":
            source_name = "ColabFold"
        elif experiment == "AF":
            source_name = "AlphaFold"
        else:
            source_name = _structure_toggle_label(experiment) or "Predicted"
        is_primary = (pdb.id == primary_pdb_id)
        is_alt = (pdb.id == alt_pdb_id)
        if is_primary:
            slot_key = "primary"
        elif is_alt:
            slot_key = "alt"
        else:
            slot_key = f"pred-{code.lower()}"
        coverage = _coverage_payload(
            getattr(link, "uniprot_start", None),
            getattr(link, "uniprot_end", None),
            protein_length,
        )
        chain_sel = _chain_selector(getattr(link, "chain", None))
        entries.append({
            "pdb_id": code,
            "source_name": source_name,
            "method": source_name,
            "resolution": "—",
            "chains": getattr(link, "chain", "") or "—",
            "links": {},
            "loaded": True,
            "loaded_structure_id": pdb.id,
            "chain_selector": chain_sel,
            "slot_key": slot_key,
            "viewer_key": "primary" if is_primary else ("alt" if is_alt else None),
            **coverage,
        })
    return entries


def _build_experimental_structures(protein, structures):
    protein_length = getattr(getattr(protein, "seq", None), "length", None) or 0
    loaded_by_code = {}
    fallback_links = []
    for link in structures:
        pdb = getattr(link, "pdb", None)
        code = str(getattr(pdb, "code", "") or "").strip().upper()
        experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
        if not code or experiment in PDB_MODEL_EXPERIMENTS:
            continue
        loaded_by_code.setdefault(code, link)
        fallback_links.append(link)

    entries = []
    seen_codes = set()
    for xref in protein.experimental_structure_xrefs.all():
        pdb_id = str(xref.pdb_id or "").strip().upper()
        if not pdb_id:
            continue
        seen_codes.add(pdb_id)
        entries.append(_experimental_structure_entry(
            pdb_id=pdb_id,
            method=xref.method,
            resolution=xref.resolution,
            chains=xref.chains,
            start=xref.uniprot_start,
            end=xref.uniprot_end,
            protein_length=protein_length,
            loaded_link=loaded_by_code.get(pdb_id),
        ))

    for link in fallback_links:
        pdb = link.pdb
        pdb_id = str(pdb.code or "").strip().upper()
        if pdb_id in seen_codes:
            continue
        method = pdb.experiment or "Experimental"
        if str(method).strip().upper() == "EX":
            method = "X-ray"
        seen_codes.add(pdb_id)
        entries.append(_experimental_structure_entry(
            pdb_id=pdb_id,
            method=method,
            resolution=link.resolution or pdb.resolution,
            chains=link.chain,
            start=link.uniprot_start,
            end=link.uniprot_end,
            protein_length=protein_length,
            loaded_link=link,
        ))

    def sort_key(entry):
        try:
            resolution = float(str(entry["resolution"]).split()[0])
        except (TypeError, ValueError, IndexError):
            resolution = 999.0
        try:
            coverage = -float(str(entry["coverage_label"]).replace("%", ""))
        except (TypeError, ValueError):
            coverage = 0.0
        return (not entry["loaded"], resolution, coverage, entry["pdb_id"])

    return sorted(entries, key=sort_key)



def serialize_prot(protein: Bioentry):
    bdb = Biodatabase.objects.filter(name=protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]).get()
    protein2 = {"id": protein.bioentry_id,
                "accession": protein.accession,
                "description": protein.description,
                "gene": " ".join(
                    g for g in protein.genes()
                    if not g.startswith(("NP_", "WP_", "XP_", "YP_", "AP_"))
                ) or " ".join(protein.genes()),
                "size": protein.seq.length,
                "assembly_id": bdb.biodatabase_id,
                "assembly_name":   bdb.name,
                "genome": genome_url_slug(bdb.name),
                "assembly_label": display_genome_name(bdb.name),
                "assembly_description": bdb.description if bdb.description else  display_genome_name(bdb.name),
                "status": "annotated",
                "seq": protein.seq.seq
                }

    features = []
    _seen_features = set()
    for feature in protein.features.all():
        location = _first_location(feature)
        if location is None:
            continue
        dedup_key = (location.start_pos, location.end_pos, feature.type_term.identifier)
        if dedup_key in _seen_features:
            continue
        _seen_features.add(dedup_key)
        features.append(
            {
                "start": location.start_pos,
                "end": location.end_pos,
                "db": feature.type_term.ontology.name,
                "fam": "",
                "term": feature.type_term.identifier,
                "name": feature.type_term.name,
            }
        )

    _TRACK_LABEL_ABBREV = {
        "SignalP_GRAM_NEGATIVE": "SignalP (GN)",
        "SignalP_GRAM_POSITIVE": "SignalP (GP)",
        "SignalP_EUK": "SignalP (Euk)",
        "MobiDBLite": "MobiDB",
    }

    graphic_features = []
    for key, group in itertools.groupby(
            sorted(protein.features.all(), key=lambda f: f.type_term.ontology.name)
            , lambda f: f.type_term.ontology.name):
        data = []
        for f in group:
            location = _first_location(f)
            if location is None:
                continue
            data.append({"x": location.start_pos,
                         "y": location.end_pos,
                         "description": f.type_term.identifier, "id": f.type_term.identifier})
        if not data:
            continue
        display_name = _TRACK_LABEL_ABBREV.get(key, key)
        gf = {
            "data": data,
            "name": display_name,
            "className": "test6",
            "color": "#81BEAA",
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)

    annotation_db_set = set(annotation_dbnames("go")) | set(annotation_dbnames("ec"))
    annotations = []
    seen_annotations = set()
    for dbx in protein.dbxrefs.all():
        dbxref = getattr(dbx, "dbxref", None)
        dbname = getattr(dbxref, "dbname", None)
        accession = str(getattr(dbxref, "accession", "") or "").strip()
        if dbname not in annotation_db_set or not accession:
            continue
        key = (dbname, accession)
        if key in seen_annotations:
            continue
        seen_annotations.add(key)
        annotations.append(
            {
                "db": dbname,
                "fam": "-",
                "term": accession,
                "name": _annotation_name(dbx),
            }
        )
    return protein2, features, annotations, graphic_features

def make_binder_svg(smiles):
    if not smiles:
        return ""
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return ""
    if mol is None:
        return ""
    drawer = rdMolDraw2D.MolDraw2DSVG(300, 300)
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def _pains_alert(mol):
    global _PAINS_CATALOG
    try:
        if _PAINS_CATALOG is None:
            params = FilterCatalogParams()
            params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
            _PAINS_CATALOG = FilterCatalog(params)
        return bool(_PAINS_CATALOG.GetFirstMatch(mol))
    except Exception:
        return False


def _binder_table_properties(smiles):
    """Small-molecule descriptors for binder tables; not a full ADMET prediction."""
    if not smiles:
        return {}
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return {}
    if mol is None:
        return {}

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    rotb = Lipinski.NumRotatableBonds(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)
    lipinski_violations = sum([
        mw > 500,
        logp > 5,
        hbd > 5,
        hba > 10,
    ])
    if lipinski_violations == 0:
        lipinski_label, lipinski_class = "✓ Ro5", "ok"
    elif lipinski_violations == 1:
        lipinski_label, lipinski_class = "1 viol.", "check"
    else:
        lipinski_label, lipinski_class = f"{lipinski_violations} viol.", "alert"

    veber_ok = rotb <= 10 and tpsa <= 140
    pains_alert = _pains_alert(mol)

    return {
        "mw": f"{mw:.1f}",
        "logp": f"{logp:.2f}",
        "tpsa": f"{tpsa:.1f}",
        "rotb": rotb,
        "lipinski_violations": lipinski_violations,
        "lipinski_label": lipinski_label,
        "lipinski_class": lipinski_class,
        "veber_ok": veber_ok,
        "pains_label": "Alert" if pains_alert else "Clear",
        "pains_alert": pains_alert,
    }


def _binder_to_dto(binder):
    return {
        "id": binder.id,
        "name": binder.ccd_id or f"Binder {binder.id}",
        "pdb": binder.pdb_id,
        "uniprot": binder.uniprot,
        "smiles": binder.smiles,
        "score": binder.score,
        "notes": binder.notes,
        "source": binder.source,
        "is_direct": binder.is_direct,
        "props": _binder_table_properties(binder.smiles),
    }


def create_binders_dict(protein, search_query=""):
    """Build a binders payload split into five categories:

    - pdb_direct    → PDB ligand, template UniProt matches this protein's own UniProt.
    - pdb_homolog   → PDB ligand found via a homologous protein.
    - chembl_direct → ChEMBL bioactivity hit on this exact protein.
    - chembl_homolog→ ChEMBL hit brought in by homology.
    - zinc          → ZINC virtual-screening candidate (tanimoto-scored).
    """
    from django.db.models import Q

    binders_qs = Binders.objects.filter(locustag=protein).order_by("source", "is_direct", "ccd_id", "id")
    cleaned_query = (search_query or "").strip()
    if cleaned_query:
        binders_qs = binders_qs.filter(
            Q(ccd_id__icontains=cleaned_query)
            | Q(pdb_id__icontains=cleaned_query)
            | Q(smiles__icontains=cleaned_query)
            | Q(notes__icontains=cleaned_query)
        )

    pdb_direct = []
    pdb_homolog = []
    chembl_direct = []
    chembl_homolog = []
    zinc = []

    for binder in binders_qs:
        dto = _binder_to_dto(binder)
        if binder.source == Binders.SOURCE_PDB:
            if binder.is_direct:
                pdb_direct.append(dto)
            else:
                pdb_homolog.append(dto)
        elif binder.source == Binders.SOURCE_CHEMBL:
            if binder.is_direct:
                chembl_direct.append(dto)
            else:
                chembl_homolog.append(dto)
        else:
            zinc.append(dto)

    score_sort = lambda e: (e["score"] is None, -(e["score"] or 0))
    chembl_direct.sort(key=score_sort)
    chembl_homolog.sort(key=score_sort)
    zinc.sort(key=score_sort)

    tab_order = ["pdb_direct", "pdb_homolog", "chembl_direct", "chembl_homolog", "zinc"]
    tab_data = {
        "pdb_direct": pdb_direct,
        "pdb_homolog": pdb_homolog,
        "chembl_direct": chembl_direct,
        "chembl_homolog": chembl_homolog,
        "zinc": zinc,
    }
    default_tab = next((t for t in tab_order if tab_data[t]), "zinc")

    total_all = sum(len(v) for v in tab_data.values())

    return {
        "pdb_direct": pdb_direct,
        "pdb_homolog": pdb_homolog,
        "chembl_direct": chembl_direct,
        "chembl_homolog": chembl_homolog,
        "zinc": zinc,
        "pdb_direct_count": len(pdb_direct),
        "pdb_homolog_count": len(pdb_homolog),
        "chembl_direct_count": len(chembl_direct),
        "chembl_homolog_count": len(chembl_homolog),
        "zinc_count": len(zinc),
        "total": total_all,
        "chembl_homolog_capped": len(chembl_homolog) >= KNOWN_BINDER_CAP,
        "zinc_capped": len(zinc) >= ZINC_BINDER_CAP,
        "default_tab": default_tab,
        "search_query": cleaned_query,
    }

class ProteinView(View):
    template_name = 'genomic/protein.html'

    @staticmethod
    def _build_view_export_url(request):
        params = request.GET.copy()
        params["export"] = "view_csv"
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else "?export=view_csv"

    def get(self, request, protein_id, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        protein = Bioentry.objects.filter(
            bioentry_id=protein_id
        ).prefetch_related("seq", "biodatabase",
                           "qualifiers__term", "dbxrefs__dbxref__terms__term",
                           "features__type_term__ontology", "features__locations",
                           "experimental_structure_xrefs",
                           "structures__pdb__residue_sets__properties__property").get()
        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Protein not found")
        proteinDTO, features, annotations, graphic_features = serialize_prot(protein)
        structures = protein.structures.prefetch_related("pdb__residues").all()
        structures = _sort_structures_by_preference(structures)
        experimental_structures = _build_experimental_structures(protein, structures)
        binders_search_query = request.GET.get("binder_search", "").strip()
        binders = create_binders_dict(protein, search_query=binders_search_query)
        structure_summary = summarize_structure_sources(structures)

        experimental_xrefs = list(
            ExperimentalStructureXref.objects
            .filter(bioentry=protein)
            .order_by("resolution")
        )
        loaded_ex_codes = {
            s.pdb.code.upper()
            for s in structures
            if (getattr(s.pdb, "experiment", "") or "").upper() == "EX"
        }
        for xref in experimental_xrefs:
            xref.is_loaded = xref.pdb_id.upper() in loaded_ex_codes
            xref.method_short = _short_method(xref.method)
        ec_all = list(iter_protein_annotations(protein, "ec"))
        go_all = list(iter_protein_annotations(protein, "go"))
        ec_badges = ec_all[:6]
        go_badges = go_all[:6]
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), proteinDTO["assembly_name"]
        )

        drugg_spv = ScoreParamValue.objects.filter(
            bioentry=protein, score_param__name="Druggability"
        ).first()
        drugg_raw = None
        if drugg_spv is not None:
            drugg_raw = drugg_spv.numeric_value if drugg_spv.numeric_value is not None else drugg_spv.value or None
        druggability = _druggability_label(drugg_raw)

        raw_scores = {
            spv.score_param.name: spv.value if spv.value else (
                str(round(spv.numeric_value, 4)) if spv.numeric_value is not None else ""
            )
            for spv in ScoreParamValue.objects.filter(bioentry=protein).select_related("score_param")
        }
        target_profile = _build_target_profile(raw_scores)
        selected_pocket_evidence = _build_selected_pocket_evidence(raw_scores)
        conservation_profile = _build_conservation_profile(raw_scores)
        microbiome_context = _build_microbiome_context(raw_scores)

        if request.GET.get("export") == "view_csv":
            sections = [
                {
                    "title": "Current view",
                    "headers": ["Field", "Value"],
                    "rows": [
                        ["Protein accession", proteinDTO["accession"]],
                        ["Protein description", proteinDTO["description"] or "-"],
                        ["Genome accession", proteinDTO["assembly_label"]],
                        ["Genome description", proteinDTO["assembly_description"]],
                        ["Gene", proteinDTO["gene"] or "-"],
                        ["Status", proteinDTO["status"]],
                        ["Amino acids", proteinDTO["size"]],
                        ["Structure source", structure_summary.get("label", "-")],
                        ["Experimental PDB entries", len(experimental_structures)],
                        ["Functional annotations", len(annotations)],
                        ["Sequence features", len(features)],
                        ["Binders", binders["total"]],
                    ],
                },
                {
                    "title": "Sequence",
                    "headers": ["Accession", "Sequence"],
                    "rows": [[proteinDTO["accession"], proteinDTO["seq"]]],
                },
            ]

            if annotations:
                sections.append(
                    {
                        "title": "Functional annotations",
                        "headers": ["DB", "Family", "Accession", "Name"],
                        "rows": [
                            [annotation["db"], annotation["fam"], annotation["term"], annotation["name"]]
                            for annotation in annotations
                        ],
                    }
                )

            if features:
                sections.append(
                    {
                        "title": "Sequence features",
                        "headers": ["Start", "End", "DB", "Term", "Name"],
                        "rows": [
                            [feature["start"], feature["end"], feature["db"], feature["term"], feature["name"]]
                            for feature in features
                        ],
                    }
                )

            if experimental_structures:
                sections.append(
                    {
                        "title": "Experimental structures",
                        "headers": [
                            "PDB", "Method", "Resolution", "Chains", "Positions",
                            "Coverage", "Loaded in TPW",
                        ],
                        "rows": [
                            [
                                entry["pdb_id"],
                                entry["method"],
                                entry["resolution"],
                                entry["chains"],
                                entry["positions"],
                                entry["coverage_label"],
                                "yes" if entry["loaded"] else "no",
                            ]
                            for entry in experimental_structures
                        ],
                    }
                )

            if binders["total"]:
                sections.append(
                    {
                        "title": "Binders",
                        "headers": ["Source", "Direct", "ID", "Name", "PDB", "UniProt", "SMILES", "Score", "Notes"],
                        "rows": [
                            [
                                binder["source"],
                                "yes" if binder["is_direct"] else "no",
                                binder["id"],
                                binder["name"],
                                binder["pdb"],
                                binder["uniprot"],
                                binder["smiles"],
                                binder["score"] if binder["score"] is not None else "",
                                binder["notes"],
                            ]
                            for binder in (
                                *binders["pdb_direct"], *binders["pdb_homolog"],
                                *binders["chembl_direct"], *binders["chembl_homolog"],
                                *binders["zinc"],
                            )
                        ],
                    }
                )

            return xlsx_sections_response(
                f"{proteinDTO['accession']}-detail-view",
                sections,
            )

        dto = {"protein": proteinDTO,
               "predicted_structures": [],
               "features": features,
               "annotations": annotations,
               "ec_annotations": ec_all,
               "go_annotations": go_all,
               "graphic_features": graphic_features,
               "binders": binders,
               "structure_summary": structure_summary,
               "experimental_structures": experimental_structures,
               "target_profile": target_profile,
               "selected_pocket_evidence": selected_pocket_evidence,
               "conservation_profile": conservation_profile,
               "microbiome_context": microbiome_context,
               "experimental_xrefs": experimental_xrefs,
               "ec_badges": ec_badges,
               "go_badges": go_badges,
               "pipeline_status": pipeline_status,
               "druggability": druggability,
               "view_export_url": self._build_view_export_url(request)}
        if structures:
            # Opción B: primary = best experimental (EX), alt = best predicted (CF/AF).
            # Ensures ColabFold is accessible even when multiple experimental PDBs
            # are loaded — the most useful comparison for biologists.
            experimental = [
                s for s in structures
                if (getattr(s.pdb, "experiment", "") or "").upper() not in _PDB_MODEL_EXPERIMENTS
            ]
            predicted = [
                s for s in structures
                if (getattr(s.pdb, "experiment", "") or "").upper() in _PDB_MODEL_EXPERIMENTS
            ]

            if experimental:
                primary_link = experimental[0]
                alt_link = predicted[0] if predicted else (
                    experimental[1] if len(experimental) > 1 else None
                )
            else:
                primary_link = predicted[0] if predicted else structures[0]
                alt_link = predicted[1] if len(predicted) > 1 else None

            protein_length = getattr(getattr(protein, "seq", None), "length", None) or 0
            primary_display = primary_link.pdb
            primary_viewer = _viewer_structure_payload(primary_link, protein_length)
            # Pocket overlays must belong to the same structure loaded first in
            # the viewer. If EX has no pockets yet, show the crystal structure
            # without pocket overlays instead of mixing AF/CF pockets onto it.
            dto["structure"] = pdb_structure(primary_display, graphic_features)
            dto["viewer_structure_id"] = primary_display.id
            dto["primary_structure_label"] = primary_viewer["short_label"]
            dto["primary_structure_detail_label"] = primary_viewer["detail_label"]
            dto["primary_structure_source_name"] = primary_viewer["source_name"]
            dto["viewer_chain"] = primary_link.chain or ""
            dto["viewer_chain_selector"] = _chain_selector(primary_link.chain)
            dto["pocket_structure_label"] = primary_viewer["short_label"]
            dto["pocket_structure_has_pockets"] = _has_pocket_data(primary_display)
            if alt_link is not None:
                alt_viewer = _viewer_structure_payload(alt_link, protein_length)
                dto["alt_structure_id"] = alt_link.pdb.id
                dto["alt_structure_label"] = alt_viewer["short_label"]
                dto["alt_structure_detail_label"] = alt_viewer["detail_label"]
                dto["alt_structure_source_name"] = alt_viewer["source_name"]
                dto["alt_structure"] = pdb_structure(alt_link.pdb, [])
                dto["alt_viewer_chain"] = alt_link.chain or ""
                dto["alt_viewer_chain_selector"] = _chain_selector(alt_link.chain)
                dto["alt_structure_has_pockets"] = _has_pocket_data(alt_link.pdb)

            visible_structure_ids = {
                primary_display.id: "primary",
            }
            if dto.get("alt_structure_id"):
                visible_structure_ids[dto["alt_structure_id"]] = "alt"
            for entry in experimental_structures:
                loaded_id = entry.get("loaded_structure_id")
                if loaded_id in visible_structure_ids:
                    entry["viewer_key"] = visible_structure_ids[loaded_id]

            for entry in experimental_structures:
                if entry.get("viewer_key"):
                    entry["slot_key"] = entry["viewer_key"]
                elif entry["loaded"]:
                    entry["slot_key"] = "ex-" + entry["pdb_id"].lower()
                else:
                    entry["slot_key"] = ""

            predicted_structures = _build_predicted_structures(predicted, protein_length, primary_link=primary_link, alt_link=alt_link)
            dto["predicted_structures"] = predicted_structures



        return render(request, self.template_name, dto)

"""Binder/ligand evidence summary for a protein.

Extracted verbatim from tpweb/views/ProteinView.py (create_binders_dict and
its private helpers) -- CLAUDE.md is explicit that views delegate to
services, not the other way around, and protein_summary.py had to import
create_binders_dict from a view via a deferred, function-local import
specifically to dodge the circular import that would otherwise cause.
Moving the whole self-contained binder cluster here removes that workaround
entirely; ProteinView.py and BinderDetailView.py now import from this
module instead of from each other.
"""

from __future__ import annotations

import re

from django.db.models import Q
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from tpweb.models.Binders import Binders

KNOWN_BINDER_CAP = 100
ZINC_BINDER_CAP = 50

_PAINS_CATALOG = None

_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUPERSCRIPT = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


def _format_molecular_formula(formula):
    """Render RDKit's raw Hill-notation formula (e.g. "H2O7P2-2") with real
    subscript element counts and a superscript charge, instead of plain
    digits with an ASCII +/- charge suffix indistinguishable from the
    formula itself."""
    if not formula:
        return formula
    charge = re.search(r"([+-])(\d*)$", formula)
    if not charge:
        return formula.translate(_SUBSCRIPT)
    base = formula[: charge.start()].translate(_SUBSCRIPT)
    # Chemistry convention writes the charge digit(s) before the sign when
    # superscripted (e.g. "2-" -> "²⁻"), the reverse of RDKit's raw order.
    magnitude, sign = charge.group(2), charge.group(1)
    return base + (magnitude + sign).translate(_SUPERSCRIPT)


def compute_binder_properties(smiles):
    """Compute physicochemical descriptors + drug-likeness from a SMILES string,
    for the binder detail page's full property panel (a superset of
    _binder_table_properties, which only computes what the compact binder-list
    table cells need)."""
    if not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return None
    if mol is None:
        return None

    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)
    tpsa = Descriptors.TPSA(mol)
    rotb = Lipinski.NumRotatableBonds(mol)
    aromatic_rings = rdMolDescriptors.CalcNumAromaticRings(mol)
    heavy_atoms = mol.GetNumHeavyAtoms()
    num_rings = rdMolDescriptors.CalcNumRings(mol)
    formula = rdMolDescriptors.CalcMolFormula(mol)
    fraction_csp3 = rdMolDescriptors.CalcFractionCSP3(mol)

    lipinski_checks = [
        {"name": "MW ≤ 500 Da", "value": f"{mw:.1f}", "ok": mw <= 500},
        {"name": "LogP ≤ 5", "value": f"{logp:.2f}", "ok": logp <= 5},
        {"name": "H-bond donors ≤ 5", "value": hbd, "ok": hbd <= 5},
        {"name": "H-bond acceptors ≤ 10", "value": hba, "ok": hba <= 10},
    ]
    lipinski_violations = sum(0 if c["ok"] else 1 for c in lipinski_checks)

    veber_checks = [
        {"name": "Rotatable bonds ≤ 10", "value": rotb, "ok": rotb <= 10},
        {"name": "TPSA ≤ 140 Å²", "value": f"{tpsa:.1f}", "ok": tpsa <= 140},
    ]
    veber_violations = sum(0 if c["ok"] else 1 for c in veber_checks)

    permeability_checks = [
        {"name": "TPSA ≤ 90 Å²", "value": f"{tpsa:.1f}", "ok": tpsa <= 90},
        {"name": "−1 ≤ LogP ≤ 5", "value": f"{logp:.2f}", "ok": -1 <= logp <= 5},
    ]
    permeability_ok = all(c["ok"] for c in permeability_checks)

    try:
        pains_params = FilterCatalogParams()
        pains_params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        pains_catalog = FilterCatalog(pains_params)
        match = pains_catalog.GetFirstMatch(mol)
        pains_hit = match.GetDescription() if match else None
    except Exception:
        pains_hit = None

    try:
        inchi = Chem.MolToInchi(mol)
        inchi_key = Chem.MolToInchiKey(mol)
    except Exception:
        inchi = ""
        inchi_key = ""

    return {
        "mw": f"{mw:.2f}",
        "logp": f"{logp:.2f}",
        "hbd": hbd,
        "hba": hba,
        "tpsa": f"{tpsa:.2f}",
        "rotb": rotb,
        "aromatic_rings": aromatic_rings,
        "heavy_atoms": heavy_atoms,
        "num_rings": num_rings,
        "formula": _format_molecular_formula(formula),
        "fraction_csp3": f"{fraction_csp3:.2f}",
        "inchi": inchi,
        "inchi_key": inchi_key,
        "lipinski_checks": lipinski_checks,
        "lipinski_violations": lipinski_violations,
        "lipinski_pass": lipinski_violations <= 1,
        "veber_checks": veber_checks,
        "veber_violations": veber_violations,
        "veber_pass": veber_violations == 0,
        "permeability_checks": permeability_checks,
        "permeability_ok": permeability_ok,
        "permeability_label": "High" if permeability_ok else "Check",
        "pains_hit": pains_hit,
    }


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
    lipinski_violations = sum(
        [
            mw > 500,
            logp > 5,
            hbd > 5,
            hba > 10,
        ]
    )
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


def _normalise_pdb_code(value):
    value = str(value or "").strip().upper()
    if not value:
        return ""
    match = re.search(r"\b([0-9][A-Z0-9]{3})\b", value)
    if match:
        return match.group(1)
    compact = re.sub(r"[^A-Z0-9]", "", value)
    if len(compact) >= 4 and compact[0].isdigit():
        return compact[:4]
    return value[:4] if len(value) >= 4 else value


def _loaded_experimental_structure_map(structures):
    loaded = {}
    for link in structures or []:
        pdb = getattr(link, "pdb", None)
        code = _normalise_pdb_code(getattr(pdb, "code", ""))
        experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
        if code and experiment == "EX":
            loaded.setdefault(code, link)
    return loaded


def _binder_crystal_payload(binder, loaded_ex_structures=None, pdb_resolution_map=None):
    pdb_code = _normalise_pdb_code(binder.pdb_id)
    loaded_link = (loaded_ex_structures or {}).get(pdb_code)
    loaded_pdb = getattr(loaded_link, "pdb", None) if loaded_link else None
    loaded_structure_id = getattr(loaded_pdb, "id", None)
    is_direct = bool(getattr(binder, "is_direct", False))
    resolution = (pdb_resolution_map or {}).get(pdb_code)

    if not pdb_code:
        return {
            "pdb_code": "",
            "loaded": False,
            "structure_id": None,
            "resolution": None,
            "status_label": "No PDB code",
            "status_tone": "external",
            "match_label": "Ligand evidence has no source PDB code.",
        }

    if loaded_structure_id:
        status_label = "Loaded crystal" if is_direct else "Loaded PDB"
        status_tone = "loaded"
        if is_direct:
            match_label = "This ligand comes from a PDB crystal already loaded for this protein."
        else:
            match_label = (
                "This source PDB is loaded for this protein, although the ligand was "
                "transferred from a homologous UniProt record."
            )
    elif is_direct:
        status_label = "External crystal"
        status_tone = "external"
        match_label = "Same-protein PDB ligand; the source crystal is available externally."
    else:
        status_label = "Homolog crystal"
        status_tone = "homolog"
        match_label = "Ligand observed in a homologous protein; use the PDB ID as source evidence."

    return {
        "pdb_code": pdb_code,
        "loaded": bool(loaded_structure_id),
        "structure_id": loaded_structure_id,
        "resolution": resolution,
        "status_label": status_label,
        "status_tone": status_tone,
        "match_label": match_label,
    }


def _binder_to_dto(binder, loaded_ex_structures=None, pdb_resolution_map=None):
    name = binder.ccd_id or f"Binder {binder.id}"
    pdb_code = _normalise_pdb_code(binder.pdb_id)
    external_url = ""
    external_label = ""
    if binder.source == Binders.SOURCE_CHEMBL and name:
        external_url = f"https://www.ebi.ac.uk/chembl/compound_report_card/{name}/"
        external_label = "ChEMBL"
    elif binder.source == Binders.SOURCE_PDB and pdb_code:
        external_url = f"https://www.rcsb.org/structure/{pdb_code}"
        external_label = "RCSB PDB"
    elif binder.source == Binders.SOURCE_PROPOSED and name:
        external_url = f"https://zinc20.docking.org/substances/{name}/"
        external_label = "ZINC"
    potency_estimate = (
        _potency_from_pchembl(binder.score)
        if binder.source == Binders.SOURCE_CHEMBL and binder.score is not None
        else ""
    )
    return {
        "id": binder.id,
        "name": name,
        "pdb": binder.pdb_id,
        "pdb_code": pdb_code,
        "uniprot": binder.uniprot,
        "smiles": binder.smiles,
        "score": binder.score,
        "potency_estimate": potency_estimate,
        "notes": binder.notes,
        "source": binder.source,
        "is_direct": binder.is_direct,
        "external_url": external_url,
        "external_label": external_label,
        "crystal": _binder_crystal_payload(binder, loaded_ex_structures, pdb_resolution_map),
        "props": _binder_table_properties(binder.smiles),
    }


def _binder_evidence_rank(item):
    source = item.get("source")
    direct = bool(item.get("is_direct"))
    score = item.get("score")
    if source == Binders.SOURCE_PDB and direct:
        tier = 0
    elif source == Binders.SOURCE_CHEMBL and direct:
        tier = 1
    elif source == Binders.SOURCE_PDB:
        tier = 2
    elif source == Binders.SOURCE_CHEMBL:
        tier = 3
    else:
        tier = 4
    return (tier, score is None, -(score or 0), item.get("name") or "")


def _binder_source_label(item):
    source = item.get("source")
    if source == Binders.SOURCE_PDB:
        return "PDB co-crystal" if item.get("is_direct") else "PDB via homolog"
    if source == Binders.SOURCE_CHEMBL:
        return "ChEMBL direct" if item.get("is_direct") else "ChEMBL via homolog"
    return "ZINC proposed compound"


def _potency_from_pchembl(pchembl):
    """pchembl_value = -log10(activity concentration in molar) is ChEMBL's own
    normalized experimental potency metric -- real affinity data already in the
    DB, just in a unit most biologists don't read at a glance. Convert back to
    a concentration (nM/uM/mM) for display alongside the raw pchembl value."""
    try:
        molar = 10 ** (-float(pchembl))
    except (TypeError, ValueError, OverflowError):
        return ""
    nanomolar = molar * 1e9
    if nanomolar < 1000:
        return f"~{nanomolar:.1f} nM"
    micromolar = nanomolar / 1000
    if micromolar < 1000:
        return f"~{micromolar:.1f} µM"
    return f"~{micromolar / 1000:.1f} mM"


def _binder_score_label(item):
    score = item.get("score")
    if score is None:
        return ""
    if item.get("source") == Binders.SOURCE_PROPOSED:
        return f"Tanimoto {score:.3f}"
    if item.get("source") == Binders.SOURCE_CHEMBL:
        potency = _potency_from_pchembl(score)
        return f"pchembl {score:.2f} ({potency})" if potency else f"pchembl {score:.2f}"
    return ""


def _build_binder_summary(tab_data):
    all_items = [
        item
        for key in ("pdb_direct", "pdb_homolog", "chembl_direct", "chembl_homolog", "zinc")
        for item in tab_data[key]
    ]
    if not all_items:
        return None

    direct_count = len(tab_data["pdb_direct"]) + len(tab_data["chembl_direct"])
    homolog_count = len(tab_data["pdb_homolog"]) + len(tab_data["chembl_homolog"])
    structural_count = len(tab_data["pdb_direct"]) + len(tab_data["pdb_homolog"])
    bioactive_count = len(tab_data["chembl_direct"]) + len(tab_data["chembl_homolog"])
    proposed_count = len(tab_data["zinc"])
    loaded_crystal_count = sum(
        1
        for item in tab_data["pdb_direct"] + tab_data["pdb_homolog"]
        if item.get("crystal", {}).get("loaded")
    )
    clean_druglike_count = sum(
        1
        for item in all_items
        if item.get("props", {}).get("lipinski_violations") == 0
        and not item.get("props", {}).get("pains_alert")
    )
    pains_alert_count = sum(1 for item in all_items if item.get("props", {}).get("pains_alert"))

    best = sorted(all_items, key=_binder_evidence_rank)[0]
    best_svg = make_binder_svg(best.get("smiles")) if best.get("smiles") else ""
    preview = []
    # Seed with the "best" pick's own key so the strip below shows other
    # ligands, not a repeat of the one already highlighted above it.
    seen = {(best.get("name"), best.get("smiles"))}
    for item in sorted(all_items, key=_binder_evidence_rank):
        name = item.get("name")
        smiles = item.get("smiles")
        key = (name, smiles)
        if key in seen:
            continue
        seen.add(key)
        preview.append(
            {
                "id": item.get("id"),
                "name": name,
                "source_label": _binder_source_label(item),
                "score_label": _binder_score_label(item),
                "external_url": item.get("external_url"),
                "external_label": item.get("external_label"),
                "svg": make_binder_svg(smiles) if smiles else "",
                "props": item.get("props") or {},
            }
        )
        if len(preview) >= 4:
            break

    if structural_count and bioactive_count:
        summary_text = "Structural and bioactivity evidence are both available for this target."
    elif structural_count:
        summary_text = "Structural ligand evidence is available for this target."
    elif bioactive_count:
        summary_text = "Bioactivity evidence is available for this target."
    elif proposed_count:
        summary_text = "Only proposed virtual-screening candidates are available for this target."
    else:
        summary_text = "Ligand evidence is available for this target."

    return {
        "direct_count": direct_count,
        "homolog_count": homolog_count,
        "structural_count": structural_count,
        "bioactive_count": bioactive_count,
        "proposed_count": proposed_count,
        "loaded_crystal_count": loaded_crystal_count,
        "clean_druglike_count": clean_druglike_count,
        "pains_alert_count": pains_alert_count,
        "best": {
            "id": best.get("id"),
            "name": best.get("name"),
            "source_label": _binder_source_label(best),
            "score_label": _binder_score_label(best),
            "external_url": best.get("external_url"),
            "external_label": best.get("external_label"),
            "svg": best_svg,
            "props": best.get("props") or {},
            "crystal": best.get("crystal") or {},
        },
        "preview": preview,
        "summary_text": summary_text,
    }


def create_binders_dict(protein, search_query="", structures=None):
    """Build a binders payload split into five categories:

    - pdb_direct    → PDB ligand, template UniProt matches this protein's own UniProt.
    - pdb_homolog   → PDB ligand found via a homologous protein.
    - chembl_direct → ChEMBL bioactivity hit on this exact protein.
    - chembl_homolog→ ChEMBL hit brought in by homology.
    - zinc          → ZINC virtual-screening candidate (tanimoto-scored).
    """
    binders_qs = Binders.objects.filter(locustag=protein).order_by(
        "source", "is_direct", "ccd_id", "id"
    )
    loaded_ex_structures = _loaded_experimental_structure_map(structures)
    pdb_resolution_map = {
        str(xref.pdb_id or "").strip().upper(): xref.resolution
        for xref in protein.experimental_structure_xrefs.all()
        if xref.resolution is not None
    }
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
        dto = _binder_to_dto(binder, loaded_ex_structures, pdb_resolution_map)
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

    def score_sort(e):
        return (e["score"] is None, -(e["score"] or 0))

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
    summary = _build_binder_summary(tab_data)

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
        "summary": summary,
    }

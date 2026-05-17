from urllib.parse import quote

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    user_can_access_genome_name,
)
from tpweb.views.ProteinView import make_binder_svg


SOURCE_LABEL = {
    Binders.SOURCE_PDB: "PDB",
    Binders.SOURCE_CHEMBL: "ChEMBL",
    Binders.SOURCE_PROPOSED: "ZINC",
}


def _compute_properties(smiles):
    """Compute physicochemical descriptors + drug-likeness from a SMILES string."""
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
        "formula": formula,
        "fraction_csp3": f"{fraction_csp3:.2f}",
        "inchi": inchi,
        "inchi_key": inchi_key,
        "lipinski_checks": lipinski_checks,
        "lipinski_violations": lipinski_violations,
        "lipinski_pass": lipinski_violations <= 1,
        "veber_checks": veber_checks,
        "veber_violations": veber_violations,
        "veber_pass": veber_violations == 0,
        "pains_hit": pains_hit,
    }


def _parse_notes(raw_notes):
    """Split LigQ_2 notes (foo | bar | baz) into structured key/value items."""
    if not raw_notes:
        return []
    parts = [p.strip() for p in raw_notes.split("|") if p.strip()]
    items = []
    for part in parts:
        if ":" in part:
            label, value = part.split(":", 1)
            items.append({"label": label.strip(), "value": value.strip()})
        elif "=" in part:
            label, value = part.split("=", 1)
            items.append({"label": label.strip(), "value": value.strip()})
        else:
            items.append({"label": "info", "value": part})
    return items


def _build_external_links(binder, props):
    """Build list of contextual external resource links."""
    links = []
    ccd_id = (binder.ccd_id or "").strip()
    ccd_upper = ccd_id.upper()
    pdb_id = (binder.pdb_id or "").strip()
    smiles = (binder.smiles or "").strip()
    inchi_key = (props or {}).get("inchi_key", "")

    if binder.source == Binders.SOURCE_PDB and ccd_id and not ccd_upper.startswith("CHEMBL"):
        links.append({
            "category": "PDB",
            "label": f"RCSB ligand {ccd_id}",
            "url": f"https://www.rcsb.org/ligand/{ccd_id}",
        })
    if pdb_id:
        links.append({
            "category": "PDB",
            "label": f"RCSB structure {pdb_id}",
            "url": f"https://www.rcsb.org/structure/{pdb_id}",
        })

    if ccd_upper.startswith("CHEMBL"):
        links.append({
            "category": "ChEMBL",
            "label": f"ChEMBL compound {ccd_id}",
            "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{ccd_id}/",
        })

    if ccd_upper.startswith("ZINC"):
        links.append({
            "category": "ZINC",
            "label": f"ZINC15 {ccd_id}",
            "url": f"https://zinc15.docking.org/substances/{ccd_id}",
        })
        links.append({
            "category": "ZINC",
            "label": f"ZINC20 {ccd_id}",
            "url": f"https://zinc20.docking.org/substances/{ccd_id}",
        })

    if binder.uniprot:
        links.append({
            "category": "UniProt",
            "label": f"UniProt {binder.uniprot} (homolog)",
            "url": f"https://www.uniprot.org/uniprotkb/{binder.uniprot}",
        })

    if inchi_key:
        links.append({
            "category": "PubChem",
            "label": "PubChem (by InChIKey)",
            "url": f"https://pubchem.ncbi.nlm.nih.gov/#query={quote(inchi_key)}",
        })
    elif smiles:
        links.append({
            "category": "PubChem",
            "label": "PubChem (by SMILES)",
            "url": f"https://pubchem.ncbi.nlm.nih.gov/#query={quote(smiles)}",
        })

    if smiles:
        links.append({
            "category": "Cheminformatics",
            "label": "SwissADME prediction",
            "url": f"http://www.swissadme.ch/index.php?smiles={quote(smiles)}",
        })
        links.append({
            "category": "Cheminformatics",
            "label": "SwissTargetPrediction",
            "url": f"http://www.swisstargetprediction.ch/result.php?smiles={quote(smiles)}&organism=Homo_sapiens",
        })

    if ccd_id:
        query = ccd_id
        links.append({
            "category": "Web",
            "label": f"Google Scholar (search “{ccd_id}”)",
            "url": f"https://scholar.google.com/scholar?q={quote(query)}",
        })

    return links


def _binder_card_dto(binder):
    return {
        "id": binder.id,
        "ccd_id": binder.ccd_id,
        "name": binder.ccd_id or f"Binder {binder.id}",
        "pdb_id": binder.pdb_id,
        "uniprot": binder.uniprot,
        "score": binder.score,
        "source": binder.source,
        "source_label": SOURCE_LABEL.get(binder.source, binder.source),
    }


def _get_siblings(binder, limit_per_source=8):
    base_qs = Binders.objects.filter(locustag=binder.locustag).exclude(id=binder.id)
    return {
        "pdb": [
            _binder_card_dto(b)
            for b in base_qs.filter(source=Binders.SOURCE_PDB).order_by("ccd_id")[:limit_per_source]
        ],
        "chembl": [
            _binder_card_dto(b)
            for b in base_qs.filter(source=Binders.SOURCE_CHEMBL).order_by("-score", "id")[:limit_per_source]
        ],
        "proposed": [
            _binder_card_dto(b)
            for b in base_qs.filter(source=Binders.SOURCE_PROPOSED).order_by("-score", "id")[:limit_per_source]
        ],
        "pdb_total": base_qs.filter(source=Binders.SOURCE_PDB).count(),
        "chembl_total": base_qs.filter(source=Binders.SOURCE_CHEMBL).count(),
        "proposed_total": base_qs.filter(source=Binders.SOURCE_PROPOSED).count(),
    }


class BinderDetailView(View):
    template_name = "genomic/binder.html"

    def get(self, request, binder_id, *args, **kwargs):
        try:
            binder = Binders.objects.select_related("locustag__biodatabase").get(pk=binder_id)
        except Binders.DoesNotExist:
            raise Http404("Binder not found")

        protein = binder.locustag
        biodb_name = protein.biodatabase.name
        prot_postfix = getattr(Biodatabase, "PROT_POSTFIX", "")
        if prot_postfix and biodb_name.endswith(prot_postfix):
            assembly_name = biodb_name[: -len(prot_postfix)]
        else:
            assembly_name = biodb_name

        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Binder not found")

        is_pdb = binder.source == Binders.SOURCE_PDB
        properties = _compute_properties(binder.smiles)
        notes_items = _parse_notes(binder.notes)
        external_links = _build_external_links(binder, properties)
        siblings = _get_siblings(binder)

        ctx = {
            "binder": {
                "id": binder.id,
                "name": binder.ccd_id or f"Binder {binder.id}",
                "ccd_id": binder.ccd_id,
                "pdb_id": binder.pdb_id,
                "uniprot": binder.uniprot,
                "smiles": binder.smiles,
                "source": binder.source,
                "source_label": SOURCE_LABEL.get(binder.source, binder.get_source_display()),
                "is_pdb": is_pdb,
                "is_direct": binder.is_direct,
                "score": binder.score,
                "notes": binder.notes,
                "notes_items": notes_items,
                "svg": make_binder_svg(binder.smiles) if binder.smiles else "",
            },
            "properties": properties,
            "external_links": external_links,
            "siblings": siblings,
            "protein": {
                "id": protein.bioentry_id,
                "accession": protein.accession,
                "description": protein.description,
            },
            "assembly_name": assembly_name,
            "assembly_label": display_genome_name(assembly_name),
            "genome": genome_url_slug(assembly_name),
            "protein_url": reverse("tpwebapp:protein", kwargs={"protein_id": protein.bioentry_id}),
            "proteins_url": reverse(
                "tpwebapp:protein_list",
                kwargs={"genome": genome_url_slug(assembly_name)},
            ),
        }
        return render(request, self.template_name, ctx)

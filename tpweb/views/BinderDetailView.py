from urllib.parse import quote

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.Binders import Binders
from tpweb.services.genome_workspace import (
    display_genome_name,
    genome_url_slug,
    user_can_access_genome_name,
)
from tpweb.services.binder_summary import (
    compute_binder_properties,
    make_binder_svg,
    _potency_from_pchembl,
)


SOURCE_LABEL = {
    Binders.SOURCE_PDB: "PDB",
    Binders.SOURCE_CHEMBL: "ChEMBL",
    Binders.SOURCE_PROPOSED: "ZINC",
}


_SOURCE_NORMALISE = {"pdb": "PDB", "chembl": "ChEMBL", "zinc": "ZINC"}

_NOTES_LABEL_MAP = {
    "info": "Method",
    "source": "Source",
    "binding_sites": "Binding sites",
    "binding_site": "Binding site",
    "uniprot_id": "UniProt",
    "uniprot": "UniProt",
    "pdb_id": "PDB structure",
    "similarity": "Similarity",
    "score": "Score",
    "e_value": "E-value",
    "identity": "Identity",
    "coverage": "Coverage",
}


def _clean_note_value(value):
    """Strip Python list/string repr: ['PF03331', 'X'] → PF03331, X"""
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        items = [s.strip().strip("'\"") for s in inner.split(",") if s.strip().strip("'\"")]
        return ", ".join(items) if items else v
    return _SOURCE_NORMALISE.get(v.lower(), v)


def _parse_notes(raw_notes):
    """Split LigQ_2 notes (foo | bar | baz) into structured key/value items."""
    if not raw_notes:
        return []
    parts = [p.strip() for p in raw_notes.split("|") if p.strip()]
    items = []
    for part in parts:
        if ":" in part:
            raw_label, value = part.split(":", 1)
        elif "=" in part:
            raw_label, value = part.split("=", 1)
        else:
            items.append({"label": "Method", "value": part})
            continue
        key = raw_label.strip().lower()
        label = _NOTES_LABEL_MAP.get(key, raw_label.strip().replace("_", " ").capitalize())
        items.append({"label": label, "value": _clean_note_value(value.strip())})
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
        links.append(
            {
                "category": "PDB",
                "label": f"RCSB ligand {ccd_id}",
                "url": f"https://www.rcsb.org/ligand/{ccd_id}",
            }
        )
    if pdb_id:
        links.append(
            {
                "category": "PDB",
                "label": f"RCSB structure {pdb_id}",
                "url": f"https://www.rcsb.org/structure/{pdb_id}",
            }
        )

    if ccd_upper.startswith("CHEMBL"):
        links.append(
            {
                "category": "ChEMBL",
                "label": f"ChEMBL compound {ccd_id}",
                "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{ccd_id}/",
            }
        )

    if ccd_upper.startswith("ZINC"):
        links.append(
            {
                "category": "ZINC",
                "label": f"ZINC15 {ccd_id}",
                "url": f"https://zinc15.docking.org/substances/{ccd_id}",
            }
        )
        links.append(
            {
                "category": "ZINC",
                "label": f"ZINC20 {ccd_id}",
                "url": f"https://zinc20.docking.org/substances/{ccd_id}",
            }
        )

    if binder.uniprot:
        uniprot_role = "same protein" if binder.is_direct else "homolog"
        links.append(
            {
                "category": "UniProt",
                "label": f"UniProt {binder.uniprot} ({uniprot_role})",
                "url": f"https://www.uniprot.org/uniprotkb/{binder.uniprot}",
            }
        )

    if inchi_key:
        links.append(
            {
                "category": "PubChem",
                "label": "PubChem (by InChIKey)",
                "url": f"https://pubchem.ncbi.nlm.nih.gov/#query={quote(inchi_key)}",
            }
        )
    elif smiles:
        links.append(
            {
                "category": "PubChem",
                "label": "PubChem (by SMILES)",
                "url": f"https://pubchem.ncbi.nlm.nih.gov/#query={quote(smiles)}",
            }
        )

    if smiles:
        links.append(
            {
                "category": "Cheminformatics",
                "label": "SwissADME prediction",
                "url": f"http://www.swissadme.ch/index.php?smiles={quote(smiles)}",
            }
        )
        links.append(
            {
                "category": "Cheminformatics",
                "label": "SwissTargetPrediction",
                "url": f"http://www.swisstargetprediction.ch/result.php?smiles={quote(smiles)}&organism=Homo_sapiens",
            }
        )

    if ccd_id:
        query = ccd_id
        links.append(
            {
                "category": "Web",
                "label": f"Google Scholar (search “{ccd_id}”)",
                "url": f"https://scholar.google.com/scholar?q={quote(query)}",
            }
        )

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
            for b in base_qs.filter(source=Binders.SOURCE_CHEMBL).order_by("-score", "id")[
                :limit_per_source
            ]
        ],
        "proposed": [
            _binder_card_dto(b)
            for b in base_qs.filter(source=Binders.SOURCE_PROPOSED).order_by("-score", "id")[
                :limit_per_source
            ]
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
        except Binders.DoesNotExist as exc:
            raise Http404("Binder not found") from exc

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
        if binder.source == Binders.SOURCE_PDB:
            evidence_label = "PDB: this protein" if binder.is_direct else "PDB: similar protein"
        elif binder.source == Binders.SOURCE_CHEMBL:
            evidence_label = (
                "ChEMBL: this protein" if binder.is_direct else "ChEMBL: similar protein"
            )
        else:
            evidence_label = "ZINC: proposed compound"
        properties = compute_binder_properties(binder.smiles)
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
                "evidence_label": evidence_label,
                "is_pdb": is_pdb,
                "is_direct": binder.is_direct,
                "score": binder.score,
                "potency_estimate": (
                    _potency_from_pchembl(binder.score)
                    if binder.source == Binders.SOURCE_CHEMBL and binder.score is not None
                    else ""
                ),
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

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
    summarize_structure_sources,
    sort_structures_by_preference as _sort_structures_by_preference,
    structure_toggle_label as _structure_toggle_label,
)

KNOWN_BINDER_CAP = 100
ZINC_BINDER_CAP = 50
_PAINS_CATALOG = None


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



def serialize_prot(protein: Bioentry):
    bdb = Biodatabase.objects.filter(name=protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]).get()
    protein2 = {"id": protein.bioentry_id,
                "accession": protein.accession,
                "description": protein.description,
                "gene": " ".join(protein.genes()),
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
                           "structures__pdb__residue_sets__properties__property").get()
        assembly_name = protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]
        if not user_can_access_genome_name(request.user, assembly_name):
            raise Http404("Protein not found")
        proteinDTO, features, annotations, graphic_features = serialize_prot(protein)
        structures = protein.structures.prefetch_related("pdb__residues").all()
        structures = _sort_structures_by_preference(structures)
        binders_search_query = request.GET.get("binder_search", "").strip()
        binders = create_binders_dict(protein, search_query=binders_search_query)
        structure_summary = summarize_structure_sources(structures)
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
                        "headers": ["Start", "End", "DB", "Family", "Term", "Name"],
                        "rows": [
                            [feature["start"], feature["end"], feature["db"], feature["fam"], feature["term"], feature["name"]]
                            for feature in features
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
               "features": features,
               "annotations": annotations,
               "ec_annotations": ec_all,
               "go_annotations": go_all,
               "graphic_features": graphic_features,
               "binders": binders,
               "structure_summary": structure_summary,
               "ec_badges": ec_badges,
               "go_badges": go_badges,
               "pipeline_status": pipeline_status,
               "druggability": druggability,
               "view_export_url": self._build_view_export_url(request)}
        if structures:
            primary_link = structures[0]
            primary_display = primary_link.pdb  # EX first if available
            # Pocket overlays must belong to the same structure loaded first in
            # the viewer. If EX has no pockets yet, show the crystal structure
            # without pocket overlays instead of mixing AF/CF pockets onto it.
            dto["structure"] = pdb_structure(primary_display, graphic_features)
            dto["viewer_structure_id"] = primary_display.id
            dto["primary_structure_label"] = _structure_toggle_label(primary_display.experiment)
            dto["viewer_chain"] = primary_link.chain or ""
            dto["viewer_chain_selector"] = _chain_selector(primary_link.chain)
            dto["pocket_structure_label"] = _structure_toggle_label(primary_display.experiment)
            dto["pocket_structure_has_pockets"] = _has_pocket_data(primary_display)
            if len(structures) > 1:
                alt_link = structures[1]
                dto["alt_structure_id"] = alt_link.pdb.id
                dto["alt_structure_label"] = _structure_toggle_label(alt_link.pdb.experiment)
                dto["alt_structure"] = pdb_structure(alt_link.pdb, [])
                dto["alt_viewer_chain"] = alt_link.chain or ""
                dto["alt_viewer_chain_selector"] = _chain_selector(alt_link.chain)
                dto["alt_structure_has_pockets"] = _has_pocket_data(alt_link.pdb)



        return render(request, self.template_name, dto)

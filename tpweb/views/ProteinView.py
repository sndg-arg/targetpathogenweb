from django.shortcuts import render
from django.http import Http404
from django.urls import reverse
from django.views import View

import itertools

from bioseq.io.BioIO import BioIO
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
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
from tpweb.services.structure_files import detect_structure_format, display_code, structure_file_path
from tpweb.services.structure_sources import (
    PDB_MODEL_EXPERIMENTS,
    summarize_structure_sources,
    sort_structures_by_preference as _sort_structures_by_preference,
    structure_toggle_label as _structure_toggle_label,
    PDB_MODEL_EXPERIMENTS as _PDB_MODEL_EXPERIMENTS,
)
from tpweb.services.protein_summary import (
    build_target_profile as _build_target_profile,
    annotate_selected_source_status as _annotate_selected_source_status,
    build_selected_pocket_evidence as _build_selected_pocket_evidence,
    build_conservation_profile as _build_conservation_profile,
    build_microbiome_context as _build_microbiome_context,
    build_metabolic_context as _build_metabolic_context,
    build_target_executive_summary as _build_target_executive_summary,
)
from tpweb.services.binder_summary import create_binders_dict


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
        label = "AlphaFold DB model"
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
        "file_format": _structure_file_format_for_link(loaded_link) if loaded_link else "pdb",
        **coverage,
    }


def _structure_source_name(experiment):
    experiment = str(experiment or "").strip().upper()
    if experiment == "EX":
        return "PDB"
    return _structure_toggle_label(experiment)


def _structure_file_format_for_link(link):
    pdb = getattr(link, "pdb", None)
    bioentry = getattr(link, "bioentry", None)
    if bioentry is None:
        return "pdb"
    biodb_name = getattr(getattr(bioentry, "biodatabase", None), "name", "") or ""
    genome = biodb_name.replace(BioIO.GENOME_PROT_POSTFIX, "")
    try:
        path = structure_file_path(genome, bioentry.accession, pdb.code)
        return detect_structure_format(path)
    except (FileNotFoundError, OSError, AttributeError):
        return "pdb"

def _viewer_structure_payload(link, protein_length):
    pdb = getattr(link, "pdb", None)
    experiment = str(getattr(pdb, "experiment", "") or "").strip().upper()
    source_name = _structure_source_name(experiment)
    code = str(getattr(pdb, "code", "") or "").strip().upper()
    clean_code = display_code(code)
    coverage = _coverage_payload(
        getattr(link, "uniprot_start", None),
        getattr(link, "uniprot_end", None),
        protein_length,
    )
    resolution = _format_resolution(getattr(link, "resolution", None) or getattr(pdb, "resolution", None))

    if source_name == "PDB" and clean_code:
        short_label = f"PDB {clean_code}"
    elif clean_code:
        short_label = f"{source_name} {clean_code}"
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
            source_name = "AlphaFold DB"
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
            "file_format": _structure_file_format_for_link(link),
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
        # Normalize _chain_X suffixes so "3E82_CHAIN_A" matches xref key "3E82"
        normalized = display_code(code)
        loaded_by_code.setdefault(normalized, link)
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
        pdb_id = display_code(str(pdb.code or "").strip().upper())
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
            coverage = -float(str(entry["coverage_label"]).replace("%", ""))
        except (TypeError, ValueError):
            coverage = 0.0
        try:
            resolution = float(str(entry["resolution"]).split()[0])
        except (TypeError, ValueError, IndexError):
            resolution = 999.0
        return (not entry["loaded"], coverage, resolution, entry["pdb_id"])

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
        binders = create_binders_dict(protein, search_query=binders_search_query, structures=structures)
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
        _annotate_selected_source_status(selected_pocket_evidence, structures)
        conservation_profile = _build_conservation_profile(raw_scores)
        microbiome_context = _build_microbiome_context(raw_scores)
        metabolic_context = _build_metabolic_context(protein, raw_scores)
        target_summary = _build_target_executive_summary(
            raw_scores,
            structure_summary,
            selected_pocket_evidence,
            conservation_profile,
            microbiome_context,
            metabolic_context,
            binders,
        )

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
                        ["3D evidence source", structure_summary.get("label", "-")],
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

        uniprot_accessions = [
            dbx.dbxref.accession
            for dbx in protein.dbxrefs.all()
            if getattr(dbx, "dbxref", None) is not None
            and dbx.dbxref.dbname in {"UnipSp", "UnipTr"}
            and dbx.dbxref.accession
        ]

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
               "target_summary": target_summary,
               "selected_pocket_evidence": selected_pocket_evidence,
               "conservation_profile": conservation_profile,
               "microbiome_context": microbiome_context,
               "metabolic_context": metabolic_context,
               "experimental_xrefs": experimental_xrefs,
               "ec_badges": ec_badges,
               "go_badges": go_badges,
               "pipeline_status": pipeline_status,
               "druggability": druggability,
               "uniprot_accessions": uniprot_accessions,
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

            _annotate_selected_source_status(selected_pocket_evidence, structures, [primary_link, alt_link])

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

from django.shortcuts import render
from django.http import Http404
from django.views import View
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

import itertools

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.Binders import Binders
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
from tpweb.services.structure_sources import summarize_structure_sources


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
                "accession": protein.name,
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
    for feature in protein.features.all():
        location = _first_location(feature)
        if location is None:
            continue
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
        gf = {
            "data": data,
            "name": key,
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

def create_binders_dict(protein):

    def make_svg(smile):
        mol = Chem.MolFromSmiles(smile)
        canvas_width_pixels = 300
        canvas_height_pixels = 300
        drawer = rdMolDraw2D.MolDraw2DSVG(canvas_width_pixels, canvas_height_pixels)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        svg_data = drawer.GetDrawingText()
        return svg_data


    binders = Binders.objects.filter(locustag=protein)
    smiles_dict = {}
    for binder in binders:
        id = binder.id
        name = binder.ccd_id
        pdb = binder.pdb_id
        smiles = binder.smiles
        svg = make_svg(smiles)
        smiles_dict[id] = {'name': name, 'pdb': pdb, 'smiles': smiles, 'svg': svg}
    return smiles_dict

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
        binders = create_binders_dict(protein)
        structure_summary = summarize_structure_sources(structures)
        ec_all = list(iter_protein_annotations(protein, "ec"))
        go_all = list(iter_protein_annotations(protein, "go"))
        ec_badges = ec_all[:6]
        go_badges = go_all[:6]
        pipeline_status = annotate_pipeline_status_for_genome(
            get_pipeline_status(), proteinDTO["assembly_name"]
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
                        ["Structure source", structure_summary.get("label", "-")],
                        ["Functional annotations", len(annotations)],
                        ["Sequence features", len(features)],
                        ["Binders", len(binders)],
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

            if binders:
                sections.append(
                    {
                        "title": "Binders",
                        "headers": ["ID", "Name", "PDB", "SMILES"],
                        "rows": [
                            [binder_id, binder["name"], binder["pdb"], binder["smiles"]]
                            for binder_id, binder in binders.items()
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
               "view_export_url": self._build_view_export_url(request)}
        if structures:
            structure = structures[0].pdb
            dto["structure"] = pdb_structure(structure,graphic_features)
            """structureDTO ={
                "id" : structure.id,
                "code" : structure.code
            }"""



        return render(request, self.template_name, dto)

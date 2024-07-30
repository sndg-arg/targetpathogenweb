from django.shortcuts import render
from django.views import View


import itertools

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Ontology import Ontology
from .StructureView import pdb_structure



def serialize_prot(protein: Bioentry):
    bdb = Biodatabase.objects.filter(name=protein.biodatabase.name.split(Biodatabase.PROT_POSTFIX)[0]).get()
    protein2 = {"accession": protein.name,
                "description": protein.description,
                "gene": " ".join(protein.genes()),
                "size": protein.seq.length,
                "assembly_id": bdb.biodatabase_id,
                "assembly_name":   bdb.name,
                "assembly_description": bdb.description if bdb.description else  bdb.name,
                "status": "annotated",
                "seq": protein.seq.seq
                }

    features = [
        {
            "start": f.locations.all()[0].start_pos,
            "end": f.locations.all()[0].end_pos,
            "db": f.type_term.ontology.name,
            "fam": "",
            "term": f.type_term.identifier,
            "name": f.type_term.name
        } for f in protein.features.all()
    ]

    graphic_features = []
    for key, group in itertools.groupby(
            sorted(protein.features.all(), key=lambda f: f.type_term.ontology.name)
            , lambda f: f.type_term.ontology.name):
        data = []
        for f in group:
            data.append({"x": f.locations.all()[0].start_pos,
                         "y": f.locations.all()[0].end_pos,
                         "description": f.type_term.identifier, "id": f.type_term.identifier})
        gf = {
            "data": data,
            "name": key,
            "className": "test6",
            "color": "#81BEAA",
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)



    annotations = [
        {
            "db": dbx.dbxref.dbname,
            "fam": "-",
            "term": dbx.dbxref.accession,
            "name": dbx.dbxref.terms.all()[0].term.definition
        } for dbx in protein.dbxrefs.all() if dbx.dbxref.dbname in [Ontology.GO, Ontology.EC]
    ]
    return protein2, features, annotations, graphic_features


class ProteinView(View):
    template_name = 'genomic/protein.html'

    def get(self, request, protein_id, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        protein = Bioentry.objects.filter(
            bioentry_id=protein_id
        ).prefetch_related("seq", "biodatabase",
                           "qualifiers__term", "dbxrefs__dbxref__terms",
                           "features__type_term__ontology", "features__locations",
                           "structures__pdb__residue_sets__properties__property").get()
        proteinDTO, features, annotations, graphic_features = serialize_prot(protein)
        structures = protein.structures.prefetch_related("pdb__residues").all()

        print(features)
        dto = {"protein": proteinDTO,
               "features": features,
               "annotations": annotations,
               "graphic_features": graphic_features}
        if structures:
            structure = structures[0].pdb
            dto["structure"] = pdb_structure(structure,graphic_features)
            """structureDTO ={
                "id" : structure.id,
                "code" : structure.code
            }"""



        return render(request, self.template_name, dto)



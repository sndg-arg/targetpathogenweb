from django.shortcuts import render
from django.views import View
from django.db.models import Q

import itertools

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Ontology import Ontology
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Property, ResidueSet, PDBResidueSet


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


def pdb_structure(pdbobj,graphic_features):
    context = {"code": pdbobj.code, "id": pdbobj.id}

    context["chains"] = [{"name": x} for x in set([r.chain for r in pdbobj.residues.all() if r.chain.strip()])]
    context["layers"] = []

    resnames = list(Residue.objects.filter(pdb=pdbobj, type=Residue.HETATOM).values("resname").distinct())
    if "HOH" in resnames or "WAT" in resnames:
        context["layers"].append("water")
    elif len([x for x in resnames if resnames not in ["HOH", "WAT"]]):
        context["layers"].append("hetero")

    from collections import defaultdict
    dna_data = defaultdict(lambda: [])
    for chain_resname in Residue.objects.filter(
            pdb=pdbobj, type="R", resname__in=["DA", "DC", "DG", "DT"]).values("chain", "resname").distinct():
        dna_data[chain_resname["chain"]].append(chain_resname["resname"])
    context["dna"] = []
    for chain, residues in dna_data.items():
        if len(residues) <= 4:
            context["layers"].append("dna")
            context["dna"] += [x for x in context["chains"] if x["name"] == chain]
            context["chains"] = [x for x in context["chains"] if x["name"] != chain]

    ds = Property.objects.get(name="druggability_score")
    rs = ResidueSet.objects.get(name="FPocketPocket")

    # sq = ResidueSetProperty.objects.select_related(pdbresidue_set)\
    #     .filter(property=ds,value__gte=0.2,pdbresidue_set=OuterRef("id"))

    context["pockets"] = PDBResidueSet.objects.prefetch_related("properties__property",
                                                                "residue_set_residue__residue__atoms").filter(
        Q(pdb=pdbobj), Q(residue_set=rs), Q(properties__property=ds) & Q(properties__value__gte=0.2)).all()
    for p in context["pockets"]:
        p.druggability = [x.value for x in p.properties.all() if x.property == ds][0]
        p.atoms = []
        p.residues = []
        data = []

        for rsr in p.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p.name, "id": p.name})
            p.residues.append(rsr.residue.resid)
            for a in rsr.residue.atoms.all():
                p.atoms.append(a.serial)
        gf = {
            "data": data,
            "name": "FPocket",
            "className": "test2",
            "color": generar_color_aleatorio(),
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)

    rss = PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue").filter(
        Q(pdb=pdbobj) &
        (~Q(residue_set__name="FPocketPocket")))
    context["residuesets"] = []
    for rs in rss:
        context["residuesets"].append({ "rs_name": rs.residue_set.name,
                                        "name": rs.name,
                                        "description": rs.description,
                                       "residues": [x.residue.resid
                                                    for x in rs.residue_set_residue.all()]})
        gf = {
            "data": [{"x":x.residue.resid,"y":x.residue.resid}
                     for x in rs.residue_set_residue.all()],
            "name": rs.name,
            "className": "test3",
            "color": generar_color_aleatorio(),
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)
    context["pdbid"] = pdbobj.code.lower()
    context["residuesets"] = sorted(context["residuesets"],key=lambda x:x["rs_name"])

    return {**context}


import random

def generar_color_aleatorio():
    # Generar valores aleatorios para los componentes RGB
    red = random.randint(0, 255)
    green = random.randint(0, 255)
    blue = random.randint(0, 255)

    # Convertir los valores RGB a formato hexadecimal
    color_hex = "#{:02X}{:02X}{:02X}".format(red, green, blue)
    return color_hex
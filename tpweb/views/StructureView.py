
from django.shortcuts import render
from django.views import View
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Property, ResidueSet, PDBResidueSet
from django.db.models import Q


class StructureView(View):
    template_name = 'genomic/structure.html'

    def get(self, request, struct_id, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        structure = PDB.objects.filter(id=struct_id).get()

        dto = {"structure": pdb_structure(structure, [])}


        return render(request, self.template_name, dto)


def pdb_structure(pdbobj, graphic_features):
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
    p2_rs = ResidueSet.objects.get(name="P2RankPocket")
    # sq = ResidueSetProperty.objects.select_related(pdbresidue_set)\
    #     .filter(property=ds,value__gte=0.2,pdbresidue_set=OuterRef("id"))

    context["pockets"] = PDBResidueSet.objects.prefetch_related("properties__property",
                                                                "residue_set_residue__residue__atoms").filter(
        Q(pdb=pdbobj), Q(residue_set=rs), Q(properties__property=ds) & Q(properties__value__gte=0.2)).all()

    context["p2_pockets"] = PDBResidueSet.objects.prefetch_related("properties__property",
                                                                "residue_set_residue__residue__atoms").filter(
        Q(pdb=pdbobj), Q(residue_set=p2_rs)).all()
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
        context["residuesets"].append({"rs_name": rs.residue_set.name,
                                       "name": rs.name,
                                       "description": rs.description,
                                       "residues": [x.residue.resid
                                                    for x in rs.residue_set_residue.all()]})
        gf = {
            "data": [{"x": x.residue.resid, "y": x.residue.resid}
                     for x in rs.residue_set_residue.all()],
            "name": "P2Rank",
            "className": "test3",
            "color": generar_color_aleatorio(),
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)
    context["pdbid"] = pdbobj.code.lower()
    context["residuesets"] = sorted(context["residuesets"], key=lambda x: x["rs_name"])

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

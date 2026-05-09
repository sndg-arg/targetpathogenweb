
from django.shortcuts import render
from django.http import Http404
from django.views import View
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Property, ResidueSet, PDBResidueSet
from django.db.models import Q
from tpweb.services.genome_workspace import user_can_access_genome_name, genome_url_slug


class StructureView(View):
    template_name = 'genomic/structure.html'

    def get(self, request, struct_id, *args, **kwargs):
        # form = self.form_class(initial=self.initial)

        structure = PDB.objects.filter(id=struct_id).get()

        dto = {"structure": pdb_structure(structure, [])}
        source_bioentry = self._resolve_source_bioentry(request, structure)
        if source_bioentry is not None:
            dto["source_protein_id"] = source_bioentry.bioentry_id
            dto["source_protein_label"] = source_bioentry.name or "Protein detail"
            source_assembly_name = self._resolve_source_assembly_name(source_bioentry)
            dto["source_assembly_name"] = source_assembly_name
            dto["source_genome"] = genome_url_slug(source_assembly_name)
            if not user_can_access_genome_name(request.user, source_assembly_name):
                raise Http404("Structure not found")


        return render(request, self.template_name, dto)

    @staticmethod
    def _resolve_source_bioentry(request, structure):
        requested_protein_id = str(request.GET.get("protein_id") or "").strip()
        if requested_protein_id.isdigit():
            link = BioentryStructure.objects.select_related("bioentry__biodatabase").filter(
                pdb=structure,
                bioentry_id=int(requested_protein_id)
            ).first()
            if link and link.bioentry:
                return link.bioentry

        first_link = BioentryStructure.objects.select_related("bioentry__biodatabase").filter(pdb=structure).first()
        if first_link and first_link.bioentry:
            return first_link.bioentry
        return None

    @staticmethod
    def _resolve_source_assembly_name(source_bioentry):
        biodb_name = getattr(getattr(source_bioentry, "biodatabase", None), "name", "") or ""
        prot_postfix = getattr(Biodatabase, "PROT_POSTFIX", "")
        if prot_postfix and biodb_name.endswith(prot_postfix):
            return biodb_name[:-len(prot_postfix)]
        if prot_postfix:
            return biodb_name.replace(prot_postfix, "")
        return biodb_name


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
    p2s = Property.objects.get(name="p2score")
    p2p = Property.objects.get(name="probability")
    rs = ResidueSet.objects.get(name="FPocketPocket")
    p2_rs = ResidueSet.objects.get(name="P2RankPocket")
    # sq = ResidueSetProperty.objects.select_related(pdbresidue_set)\
    #     .filter(property=ds,value__gte=0.2,pdbresidue_set=OuterRef("id"))

    context["pockets"] = list(PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue__atoms",
    ).filter(
        Q(pdb=pdbobj), Q(residue_set=rs), Q(properties__property=ds) & Q(properties__value__gte=0.2)
    ))

    context["p2_pockets"] = list(PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue__atoms",
    ).filter(Q(pdb=pdbobj), Q(residue_set=p2_rs)))
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

    context["pockets"].sort(key=lambda p: p.druggability or 0, reverse=True)

    for p2 in context["p2_pockets"]:
        p2.p2score = [x.value for x in p2.properties.all() if x.property == p2s][0]
        p2.probability = [x.value for x in p2.properties.all() if x.property == p2p][0]
        p2.atoms = []
        p2.residues = []
        data = []

        for rsr in p2.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p2.name, "id": p2.name})
            p2.residues.append(rsr.residue.resid)
            for a in rsr.residue.atoms.all():
                p2.atoms.append(a.serial)
        gf_p2 = {
            "data": data,
            "name": "P2Pocket",
            "className": "test2",
            "color": p2rank_probability_color(p2.probability),
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf_p2)

    context["p2_pockets"].sort(key=lambda p: p.probability or 0, reverse=True)

    ## Non pocket res
    rss = PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue").filter(
        Q(pdb=pdbobj) &
        (~Q(residue_set__name="FPocketPocket")) &
        (~Q(residue_set__name="P2RankPocket")))
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


def p2rank_probability_color(probability):
    """Return a hex color based on P2Rank calibrated probability thresholds.

    High (>= 0.5): green — strong binding-site prediction.
    Medium (>= 0.2): amber — moderate prediction.
    Low (< 0.2): red — weak prediction.
    """
    try:
        prob = float(probability)
    except (TypeError, ValueError):
        return "#F59E0B"  # amber fallback
    if prob >= 0.5:
        return "#10B981"  # green
    if prob >= 0.2:
        return "#F59E0B"  # amber
    return "#EF4444"      # red


def generar_color_aleatorio():
    # Generar valores aleatorios para los componentes RGB
    red = random.randint(0, 255)
    green = random.randint(0, 255)
    blue = random.randint(0, 255)

    # Convertir los valores RGB a formato hexadecimal
    color_hex = "#{:02X}{:02X}{:02X}".format(red, green, blue)
    return color_hex

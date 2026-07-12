
from django.shortcuts import render
from django.http import Http404
from django.views import View
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Property, ResidueSet, PDBResidueSet, ResidueSetProperty
from django.db.models import Q
from tpweb.services.genome_workspace import user_can_access_genome_name, genome_url_slug
from tpweb.services.structure_files import detect_structure_format, display_code, structure_file_path
from tpweb.services.pocket_geometry import volume_outlier_map


_METHOD_MAP = {"EX": "Crystal structure", "AF": "AlphaFold DB model", "CF": "ColabFold model"}
_SHORT_METHOD = {"EX": "Crystal", "AF": "AlphaFold DB", "CF": "ColabFold"}
_FPOCKET_INSPECTOR_PROPERTIES = [
    ("Volume", "Volume"),
    ("Score", "FPocket score"),
    ("Number of Alpha Spheres", "Alpha spheres"),
    ("Total SASA", "Total SASA"),
    ("Apolar alpha sphere proportion", "Apolar spheres"),
    ("Mean local hydrophobic density", "Hydrophobic density"),
    ("Mean alpha sphere radius", "Mean sphere radius"),
    ("Flexibility", "Flexibility"),
]
_P2RANK_INSPECTOR_PROPERTIES = [
    ("p2score", "P2Rank score"),
]


def _chain_selector(chain):
    chain = (chain or "").strip()
    return f":{chain}" if chain else "polymer"


def _format_float(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(num) >= 100:
        return f"{num:.0f}"
    if abs(num) >= 10:
        return f"{num:.1f}"
    return f"{num:.2f}".rstrip("0").rstrip(".")


def _residue_set_property_map(residue_set):
    return {
        prop.property.name: prop.value
        for prop in residue_set.properties.all()
        if prop.property_id and prop.value is not None
    }


def _inspector_property_summary(residue_set, wanted_properties):
    prop_map = _residue_set_property_map(residue_set)
    items = []
    for prop_name, label in wanted_properties:
        value = _format_float(prop_map.get(prop_name))
        if value:
            items.append(f"{label}: {value}")
    return " | ".join(items)


def _residue_set_core_atoms(residue_set):
    atoms = []
    for rsr in residue_set.residue_set_residue.all():
        for atom_set in rsr.atoms.all():
            if atom_set.atom_id:
                atoms.append(atom_set.atom.serial)
    return atoms


# FPocket alpha-sphere radii ordinarily fall in this range; used only as a
# defensive clamp for bad/missing data, not to model real sphere sizes.
_ALPHA_SPHERE_MIN_RADIUS = 1.0
_ALPHA_SPHERE_MAX_RADIUS = 6.5
_ALPHA_SPHERE_FALLBACK_RADIUS = 2.5


def _atom_points(atoms, use_bfactor_radius=False):
    points = []
    seen = set()
    for atom in atoms:
        if atom.id in seen:
            continue
        seen.add(atom.id)
        if use_bfactor_radius and atom.bfactor and atom.bfactor > 0.3:
            radius = min(max(atom.bfactor, _ALPHA_SPHERE_MIN_RADIUS), _ALPHA_SPHERE_MAX_RADIUS)
        else:
            radius = _ALPHA_SPHERE_FALLBACK_RADIUS if use_bfactor_radius else 1.0
        points.append({
            "x": f"{atom.x:.4f}",
            "y": f"{atom.y:.4f}",
            "z": f"{atom.z:.4f}",
            # FPocket writes each alpha sphere's real radius into the STP
            # pseudo-atom's B-factor column. Only meaningful for FPocket
            # alpha-sphere atoms -- callers rendering real residue atoms
            # (e.g. P2Rank's core_points) must not use this as a radius,
            # since bfactor there is a genuine crystallographic/predicted
            # B-factor, not a sphere size.
            "radius": f"{radius:.3f}",
        })
    return points


def _point_float(point, coord):
    try:
        return float(point.get(coord))
    except (TypeError, ValueError):
        return None


def _points_are_near_residue_cloud(core_points, residue_points, threshold=8.0):
    """Guard against showing imported pocket geometry on the wrong structure."""
    if not core_points or not residue_points:
        return False
    threshold_sq = threshold * threshold
    residue_coords = []
    for point in residue_points[:600]:
        x = _point_float(point, "x")
        y = _point_float(point, "y")
        z = _point_float(point, "z")
        if x is not None and y is not None and z is not None:
            residue_coords.append((x, y, z))
    if not residue_coords:
        return False
    for point in core_points[:250]:
        x = _point_float(point, "x")
        y = _point_float(point, "y")
        z = _point_float(point, "z")
        if x is None or y is None or z is None:
            continue
        for rx, ry, rz in residue_coords:
            dx = x - rx
            dy = y - ry
            dz = z - rz
            if dx * dx + dy * dy + dz * dz <= threshold_sq:
                return True
    return False


def _residue_set_core_points(residue_set):
    atoms = []
    for rsr in residue_set.residue_set_residue.all():
        for atom_set in rsr.atoms.all():
            if atom_set.atom_id:
                atoms.append(atom_set.atom)
    return _atom_points(atoms)


def _fpocket_alpha_points(pdbobj, pocket_name):
    try:
        pocket_resid = int(pocket_name)
    except (TypeError, ValueError):
        return []
    alpha_residues = Residue.objects.prefetch_related("atoms").filter(
        pdb=pdbobj,
        resname="STP",
        resid=pocket_resid,
    )
    atoms = []
    for residue in alpha_residues:
        atoms.extend(residue.atoms.all())
    return _atom_points(atoms, use_bfactor_radius=True)


class StructureView(View):
    template_name = 'genomic/structure.html'

    def get(self, request, struct_id, *args, **kwargs):
        structure = PDB.objects.filter(id=struct_id).get()
        primary_data = pdb_structure(structure, [])

        dto = {"structure": primary_data}

        source_bioentry = self._resolve_source_bioentry(request, structure)
        if source_bioentry is not None:
            dto["source_protein_id"] = source_bioentry.bioentry_id
            dto["source_protein_label"] = source_bioentry.name or "Protein detail"
            source_assembly_name = self._resolve_source_assembly_name(source_bioentry)
            dto["source_assembly_name"] = source_assembly_name
            dto["source_genome"] = genome_url_slug(source_assembly_name)
            if not user_can_access_genome_name(request.user, source_assembly_name):
                raise Http404("Structure not found")

            # Collect ALL structures linked to this protein
            all_links = (
                BioentryStructure.objects
                .select_related("pdb")
                .filter(bioentry=source_bioentry)
                .order_by("pdb__experiment", "pdb__code")
            )

            all_structures = []
            seen_ids = set()
            for link in all_links:
                pdb = link.pdb
                if pdb.id in seen_ids:
                    continue
                seen_ids.add(pdb.id)
                s_data = primary_data if pdb.id == structure.id else pdb_structure(pdb, [])
                exp = (pdb.experiment or "").upper()
                all_structures.append({
                    "id": pdb.id,
                    "code": pdb.code,
                    "display_code": display_code(pdb.code),
                    "experiment": exp,
                    "method": s_data["method"],
                    "short_method": _SHORT_METHOD.get(exp, s_data["method"]),
                    "resolution": s_data.get("resolution"),
                    "chain_selector": _chain_selector(link.chain),
                    "file_format": self._structure_file_format(link.bioentry, pdb),
                    "structure_data": s_data,
                    "is_active": pdb.id == structure.id,
                })

            # Ensure the requested structure is always in the list
            if not any(s["id"] == structure.id for s in all_structures):
                primary_link = BioentryStructure.objects.filter(
                    pdb=structure, bioentry=source_bioentry
                ).first()
                chain_sel = _chain_selector(primary_link.chain if primary_link else "")
                exp = (structure.experiment or "").upper()
                all_structures.insert(0, {
                    "id": structure.id,
                    "code": structure.code,
                    "display_code": display_code(structure.code),
                    "experiment": exp,
                    "method": primary_data["method"],
                    "short_method": _SHORT_METHOD.get(exp, primary_data["method"]),
                    "resolution": primary_data.get("resolution"),
                    "chain_selector": chain_sel,
                    "file_format": self._structure_file_format(source_bioentry, structure),
                    "structure_data": primary_data,
                    "is_active": True,
                })

            dto["all_structures"] = all_structures
            active = next((s for s in all_structures if s["is_active"]), all_structures[0] if all_structures else None)
            if active:
                dto["viewer_chain_selector"] = active["chain_selector"]
        else:
            exp = (structure.experiment or "").upper()
            dto["all_structures"] = [{
                "id": structure.id,
                "code": structure.code,
                "display_code": display_code(structure.code),
                "experiment": exp,
                "method": primary_data["method"],
                "short_method": _SHORT_METHOD.get(exp, primary_data["method"]),
                "resolution": primary_data.get("resolution"),
                "chain_selector": "polymer",
                "file_format": self._structure_file_format(None, structure),
                "structure_data": primary_data,
                "is_active": True,
            }]
            dto["viewer_chain_selector"] = "polymer"

        return render(request, self.template_name, dto)

    @staticmethod
    def _structure_file_format(source_bioentry, structure):
        if source_bioentry is None:
            source_link = BioentryStructure.objects.select_related("bioentry__biodatabase").filter(
                pdb=structure
            ).first()
            source_bioentry = source_link.bioentry if source_link else None
        if source_bioentry is None:
            return "pdb"
        assembly_name = StructureView._resolve_source_assembly_name(source_bioentry)
        try:
            path = structure_file_path(assembly_name, source_bioentry.accession, structure.code)
            return detect_structure_format(path)
        except (FileNotFoundError, OSError, AttributeError):
            return "pdb"
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


def _ranked_pocket_ids(pdbobj, residue_set, property_obj, limit, min_value=None):
    qs = PDBResidueSet.objects.filter(
        pdb=pdbobj,
        residue_set=residue_set,
        properties__property=property_obj,
    )
    if min_value is not None:
        qs = qs.filter(properties__value__gte=min_value)
    qs = qs.order_by("-properties__value", "name").values_list("id", flat=True)
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def pdb_structure(
    pdbobj,
    graphic_features,
    pocket_limit=4,
    p2rank_limit=5,
    include_pockets_in_graphic_features=False,
):
    context = {"code": pdbobj.code, "display_code": display_code(pdbobj.code), "id": pdbobj.id}

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

    # Compare every FPocket pocket's volume against its OWN structure's other
    # pockets (not the top-N shown in the UI, nor a fixed global cutoff) --
    # what counts as "unusually large" varies by protein.
    volume_prop = Property.objects.filter(name="Volume").first()
    size_outlier_map = {}
    if volume_prop is not None:
        all_volumes = ResidueSetProperty.objects.filter(
            pdbresidue_set__pdb=pdbobj,
            pdbresidue_set__residue_set=rs,
            property=volume_prop,
        ).values_list("pdbresidue_set_id", "value")
        size_outlier_map = volume_outlier_map(all_volumes)

    pocket_ids = _ranked_pocket_ids(pdbobj, rs, ds, pocket_limit, min_value=0.2)
    p2_pocket_ids = _ranked_pocket_ids(pdbobj, p2_rs, p2p, p2rank_limit)

    context["pockets"] = list(PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue__atoms",
        "residue_set_residue__atoms__atom",
    ).filter(id__in=pocket_ids))

    context["p2_pockets"] = list(PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue__atoms",
        "residue_set_residue__atoms__atom",
    ).filter(id__in=p2_pocket_ids))
    for p in context["pockets"]:
        p.druggability = [x.value for x in p.properties.all() if x.property == ds][0]
        p.atoms = []
        p.core_atoms = _residue_set_core_atoms(p)
        residue_core_points = _residue_set_core_points(p)
        alpha_core_points = _fpocket_alpha_points(pdbobj, p.name)
        if alpha_core_points and _points_are_near_residue_cloud(alpha_core_points, residue_core_points):
            p.core_points = alpha_core_points
            p.core_geometry = "alpha_spheres"
            p.core_button_label = "Alpha spheres"
            p.core_layer_label = "Alpha spheres / pocket core"
            p.core_note = "Specific FPocket alpha-sphere geometry imported for this structure."
        else:
            p.core_points = residue_core_points
            p.core_geometry = "residue_atoms"
            p.core_button_label = "Pocket atoms"
            p.core_layer_label = "Pocket atoms / specific pocket"
            p.core_note = "Alpha-sphere geometry was unavailable or did not align with this loaded structure; showing pocket atoms instead."

        is_outlier, median_volume, _mad = size_outlier_map.get(p.id, (False, None, None))
        p.size_outlier = is_outlier
        if is_outlier:
            pocket_volume = next((x.value for x in p.properties.all() if x.property == volume_prop), None)
            p.size_outlier_note = (
                f"This pocket's volume ({pocket_volume:.0f} Å³) is unusually large/diffuse compared to "
                f"this structure's other pockets (typical volume ~{median_volume:.0f} Å³) — may reflect a "
                "low-confidence or disordered model region rather than a real small-molecule cavity."
                if pocket_volume is not None and median_volume is not None
                else "This pocket's geometry is unusually large/diffuse compared to this structure's other "
                "pockets — may reflect a low-confidence or disordered model region rather than a real "
                "small-molecule cavity."
            )
        else:
            p.size_outlier_note = ""
        p.residues = []
        data = []

        for rsr in p.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p.name, "id": p.name})
            p.residues.append(rsr.residue.resid)
            for a in rsr.residue.atoms.all():
                p.atoms.append(a.serial)
        if include_pockets_in_graphic_features:
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
    for p in context["pockets"]:
        p.inspector_properties = _inspector_property_summary(p, _FPOCKET_INSPECTOR_PROPERTIES)

    for p2 in context["p2_pockets"]:
        p2.p2score = [x.value for x in p2.properties.all() if x.property == p2s][0]
        p2.probability = [x.value for x in p2.properties.all() if x.property == p2p][0]
        p2.atoms = []
        p2.core_atoms = _residue_set_core_atoms(p2)
        p2.core_points = _residue_set_core_points(p2)
        p2.residues = []
        data = []

        for rsr in p2.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p2.name, "id": p2.name})
            p2.residues.append(rsr.residue.resid)
            for a in rsr.residue.atoms.all():
                p2.atoms.append(a.serial)
        if include_pockets_in_graphic_features:
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
    for p2 in context["p2_pockets"]:
        p2.inspector_properties = _inspector_property_summary(p2, _P2RANK_INSPECTOR_PROPERTIES)

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

    context["method"] = _METHOD_MAP.get((pdbobj.experiment or "").upper(), "Structure model")
    try:
        res_val = float(pdbobj.resolution)
        context["resolution"] = f"{res_val:.1f}" if 0 < res_val < 15 else None
    except (TypeError, ValueError):
        context["resolution"] = None

    return {**context}


import random


def p2rank_probability_color(probability):
    try:
        prob = float(probability)
    except (TypeError, ValueError):
        return "#F59E0B"
    if prob >= 0.5:
        return "#10B981"
    if prob >= 0.2:
        return "#F59E0B"
    return "#EF4444"


def generar_color_aleatorio():
    red = random.randint(0, 255)
    green = random.randint(0, 255)
    blue = random.randint(0, 255)
    color_hex = "#{:02X}{:02X}{:02X}".format(red, green, blue)
    return color_hex

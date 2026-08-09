
import math

from django.shortcuts import render
from django.http import Http404
from django.views import View
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB, Residue, Property, ResidueSet, PDBResidueSet, ResidueSetProperty
from django.db.models import FilteredRelation, Q
from tpweb.services.genome_workspace import user_can_access_genome_name, genome_url_slug
from tpweb.services.structure_files import detect_structure_format, disambiguate_display_codes, display_code, structure_file_path
from tpweb.services.structure_sources import chain_selector as _chain_selector, is_multichain as _is_multichain
from tpweb.services.pocket_geometry import volume_outlier_map, filter_pdbresidueset_by_chain


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

# Property/ResidueSet rows below are fixed vocabulary defined by the pipeline
# import code (druggability_score, p2score, probability properties; the
# FPocketPocket/P2RankPocket residue-set kinds) -- identical for every
# structure and every request, effectively never edited at runtime. Loading
# them once per worker process instead of re-querying (6 queries) on every
# pdb_structure() call. If one of these rows is ever renamed/added through an
# admin action rather than a pipeline import, a worker restart picks it up.
_pdb_reference_rows_cache = None


def _pdb_reference_rows():
    global _pdb_reference_rows_cache
    if _pdb_reference_rows_cache is None:
        _pdb_reference_rows_cache = {
            "druggability_score": Property.objects.get(name="druggability_score"),
            "p2score": Property.objects.get(name="p2score"),
            "probability": Property.objects.get(name="probability"),
            "FPocketPocket": ResidueSet.objects.get(name="FPocketPocket"),
            "P2RankPocket": ResidueSet.objects.get(name="P2RankPocket"),
            "volume": Property.objects.filter(name="volume").first(),
        }
    return _pdb_reference_rows_cache


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


def _points_are_near_residue_cloud(core_points, residue_points, threshold=5.0, min_fraction=0.6):
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
    checked = 0
    near = 0
    for point in core_points[:250]:
        x = _point_float(point, "x")
        y = _point_float(point, "y")
        z = _point_float(point, "z")
        if x is None or y is None or z is None:
            continue
        checked += 1
        for rx, ry, rz in residue_coords:
            dx = x - rx
            dy = y - ry
            dz = z - rz
            if dx * dx + dy * dy + dz * dz <= threshold_sq:
                near += 1
                break
    return checked > 0 and (near / checked) >= min_fraction


def _residue_set_core_points(residue_set):
    atoms = []
    for rsr in residue_set.residue_set_residue.all():
        for atom_set in rsr.atoms.all():
            if atom_set.atom_id:
                atoms.append(atom_set.atom)
    return _atom_points(atoms)


# Two pocket-core centers within this range are treated as predicting the same
# binding site, regardless of method (FPocket alpha-sphere cloud vs P2Rank residue cloud).
_POCKET_CONSENSUS_DISTANCE = 8.0


def _pocket_center(points):
    coords = []
    for point in points or []:
        x = _point_float(point, "x")
        y = _point_float(point, "y")
        z = _point_float(point, "z")
        if x is not None and y is not None and z is not None:
            coords.append((x, y, z))
    if not coords:
        return None
    n = len(coords)
    return (
        sum(c[0] for c in coords) / n,
        sum(c[1] for c in coords) / n,
        sum(c[2] for c in coords) / n,
    )


def _center_distance(a, b):
    if a is None or b is None:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _nearest_named_center(center, named_centers):
    """named_centers: [(label, center), ...]. Returns (label, distance) for the closest, or None."""
    best = None
    for label, other in named_centers:
        distance = _center_distance(center, other)
        if distance is None:
            continue
        if best is None or distance < best[1]:
            best = (label, distance)
    return best


def _residue_identity(residue):
    """Stable residue identity for cross-method pocket comparisons."""
    return (
        str(getattr(residue, "chain", "") or "").strip(),
        int(getattr(residue, "resid")),
        str(getattr(residue, "icode", "") or "").strip(),
    )


def _residue_display_label(residue):
    """Amino-acid code + residue number for display (e.g. 'Asp123'), instead of
    the bare residue number -- falls back to just the number when resname is
    missing (e.g. a non-standard/unparsed residue)."""
    resname = str(getattr(residue, "resname", "") or "").strip()
    resid = getattr(residue, "resid", "")
    return f"{resname.capitalize()}{resid}" if resname else str(resid)


def _pocket_residue_overlap(left_residues, right_residues):
    """Return overlap metrics without conflating equal numbers across chains."""
    left = {_residue_identity(residue) for residue in left_residues}
    right = {_residue_identity(residue) for residue in right_residues}
    shared = left & right
    union = left | right
    smaller = min(len(left), len(right))
    return {
        "shared_count": len(shared),
        "smaller_coverage": (len(shared) / smaller * 100.0) if smaller else 0.0,
        "jaccard": (len(shared) / len(union) * 100.0) if union else 0.0,
    }


def _format_pocket_center(center):
    if center is None:
        return ""
    return f"Center: ({center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f})"


def _join_nonempty(parts, sep=" | "):
    return sep.join(part for part in parts if part)


def _annotated_site_label(residue_set):
    source = str(residue_set.get("rs_name") or "").strip()
    site_name = str(residue_set.get("name") or "").strip()
    return ": ".join(part for part in (source, site_name) if part)


class StructureView(View):
    template_name = 'genomic/structure.html'

    def get(self, request, struct_id, *args, **kwargs):
        structure = PDB.objects.filter(id=struct_id).get()
        source_bioentry = self._resolve_source_bioentry(request, structure)

        primary_link = None
        if source_bioentry is not None:
            primary_link = BioentryStructure.objects.filter(
                pdb=structure, bioentry=source_bioentry
            ).first()
        primary_chain = (primary_link.chain or "").strip() if primary_link else ""
        primary_data = pdb_structure(structure, [], target_chain=primary_chain or None)

        dto = {"structure": primary_data}

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
                link_chain = (link.chain or "").strip()
                s_data = primary_data if pdb.id == structure.id else pdb_structure(pdb, [], target_chain=link_chain or None)
                exp = (pdb.experiment or "").upper()
                multichain = _is_multichain(link.chain, s_data)
                all_structures.append({
                    "id": pdb.id,
                    "code": pdb.code,
                    "display_code": display_code(pdb.code),
                    "experiment": exp,
                    "method": s_data["method"],
                    "short_method": _SHORT_METHOD.get(exp, s_data["method"]),
                    "resolution": s_data.get("resolution"),
                    "chain_selector": _chain_selector(link.chain),
                    "is_multichain": multichain,
                    "chain_color_default": exp == "EX" and multichain,
                    "file_format": self._structure_file_format(link.bioentry, pdb),
                    "structure_data": s_data,
                    "is_active": pdb.id == structure.id,
                })

            # Ensure the requested structure is always in the list
            if not any(s["id"] == structure.id for s in all_structures):
                primary_chain_value = primary_link.chain if primary_link else ""
                chain_sel = _chain_selector(primary_chain_value)
                exp = (structure.experiment or "").upper()
                multichain = _is_multichain(primary_chain_value, primary_data)
                all_structures.insert(0, {
                    "id": structure.id,
                    "code": structure.code,
                    "display_code": display_code(structure.code),
                    "experiment": exp,
                    "method": primary_data["method"],
                    "short_method": _SHORT_METHOD.get(exp, primary_data["method"]),
                    "resolution": primary_data.get("resolution"),
                    "chain_selector": chain_sel,
                    "is_multichain": multichain,
                    "chain_color_default": exp == "EX" and multichain,
                    "file_format": self._structure_file_format(source_bioentry, structure),
                    "structure_data": primary_data,
                    "is_active": True,
                })

            disambiguate_display_codes(all_structures)
            dto["all_structures"] = all_structures
            active = next((s for s in all_structures if s["is_active"]), all_structures[0] if all_structures else None)
            if active:
                dto["viewer_chain_selector"] = active["chain_selector"]
        else:
            exp = (structure.experiment or "").upper()
            multichain = _is_multichain("", primary_data)
            dto["all_structures"] = [{
                "id": structure.id,
                "code": structure.code,
                "display_code": display_code(structure.code),
                "experiment": exp,
                "method": primary_data["method"],
                "short_method": _SHORT_METHOD.get(exp, primary_data["method"]),
                "resolution": primary_data.get("resolution"),
                "chain_selector": "polymer",
                "is_multichain": multichain,
                "chain_color_default": exp == "EX" and multichain,
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


def _ranked_pocket_ids(pdbobj, residue_set, property_obj, limit, min_value=None, target_chain=None):
    # FilteredRelation gives this join a name (rank_prop) scoped to exactly
    # property=property_obj, so the value filter/order below can't bind to a
    # *different* property on the same pocket -- two separate .filter() calls
    # spanning the same multi-valued "properties" relation would each get
    # their own independent join (Django's documented behavior), letting a
    # pocket pass min_value via some unrelated property (volume, alpha-sphere
    # count, ...) regardless of its real druggability/p2rank score.
    qs = (
        PDBResidueSet.objects.filter(pdb=pdbobj, residue_set=residue_set)
        .annotate(rank_prop=FilteredRelation("properties", condition=Q(properties__property=property_obj)))
        .filter(rank_prop__isnull=False)
    )
    if min_value is not None:
        qs = qs.filter(rank_prop__value__gte=min_value)
    qs = filter_pdbresidueset_by_chain(qs, target_chain)
    qs = qs.order_by("-rank_prop__value", "name").values_list("id", flat=True)
    if limit is not None:
        qs = qs[:limit]
    return list(qs)


def pdb_structure(
    pdbobj,
    graphic_features,
    pocket_limit=4,
    p2rank_limit=5,
    include_pockets_in_graphic_features=False,
    target_chain=None,
):
    context = {"code": pdbobj.code, "display_code": display_code(pdbobj.code), "id": pdbobj.id}

    chain_names = (
        Residue.objects.filter(pdb=pdbobj).exclude(chain="").values_list("chain", flat=True).distinct()
    )
    context["chains"] = [{"name": chain} for chain in chain_names if chain.strip()]
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

    ref = _pdb_reference_rows()
    ds = ref["druggability_score"]
    p2s = ref["p2score"]
    p2p = ref["probability"]
    rs = ref["FPocketPocket"]
    p2_rs = ref["P2RankPocket"]

    # Compare every FPocket pocket's volume against its OWN structure's other
    # pockets (not the top-N shown in the UI, nor a fixed global cutoff) --
    # what counts as "unusually large" varies by protein.
    volume_prop = ref["volume"]
    size_outlier_map = {}
    if volume_prop is not None:
        all_volumes = ResidueSetProperty.objects.filter(
            pdbresidue_set__pdb=pdbobj,
            pdbresidue_set__residue_set=rs,
            property=volume_prop,
        ).values_list("pdbresidue_set_id", "value")
        size_outlier_map = volume_outlier_map(all_volumes)

    pocket_ids = _ranked_pocket_ids(pdbobj, rs, ds, pocket_limit, min_value=0.2, target_chain=target_chain)
    p2_pocket_ids = _ranked_pocket_ids(pdbobj, p2_rs, p2p, p2rank_limit, target_chain=target_chain)

    # pocket_ids/p2_pocket_ids come from two different residue-set kinds
    # (FPocketPocket vs P2RankPocket), so their id sets never overlap -- fetch
    # both in one query instead of two identical-shaped ones, then split back
    # out by id while preserving each list's own ranked order.
    pockets_by_id = {
        obj.id: obj
        for obj in PDBResidueSet.objects.prefetch_related(
            "properties__property",
            "residue_set_residue__residue__atoms",
            "residue_set_residue__atoms__atom",
        ).filter(id__in=pocket_ids + p2_pocket_ids)
    }
    context["pockets"] = [pockets_by_id[i] for i in pocket_ids if i in pockets_by_id]
    context["p2_pockets"] = [pockets_by_id[i] for i in p2_pocket_ids if i in pockets_by_id]

    # FPocket alpha-sphere geometry lives on Residue rows named "STP", one per
    # pocket, keyed by resid == the pocket's own name/number. Bulk-fetch every
    # pocket's alpha residues in one query instead of one query per pocket
    # inside the loop below (was up to pocket_limit=4 extra queries per call).
    pocket_resids = []
    for p in context["pockets"]:
        try:
            pocket_resids.append(int(p.name))
        except (TypeError, ValueError):
            pass
    alpha_atoms_by_resid = defaultdict(list)
    if pocket_resids:
        for residue in Residue.objects.prefetch_related("atoms").filter(
            pdb=pdbobj, resname="STP", resid__in=pocket_resids
        ):
            alpha_atoms_by_resid[residue.resid].extend(residue.atoms.all())

    for p in context["pockets"]:
        p.druggability = [x.value for x in p.properties.all() if x.property == ds][0]
        p.atoms = []
        p.core_atoms = _residue_set_core_atoms(p)
        residue_core_points = _residue_set_core_points(p)
        try:
            pocket_resid = int(p.name)
        except (TypeError, ValueError):
            pocket_resid = None
        alpha_core_points = (
            _atom_points(alpha_atoms_by_resid.get(pocket_resid, []), use_bfactor_radius=True)
            if pocket_resid is not None else []
        )
        if alpha_core_points and _points_are_near_residue_cloud(alpha_core_points, residue_core_points):
            p.core_points = alpha_core_points
            p.core_geometry = "alpha_spheres"
            p.core_button_label = "Alpha spheres"
            p.core_layer_label = "Alpha spheres / pocket core"
            p.core_note = "Specific FPocket alpha-sphere geometry imported for this structure."
        elif residue_core_points:
            p.core_points = residue_core_points
            p.core_geometry = "residue_atoms"
            p.core_button_label = "Pocket atoms"
            p.core_layer_label = "Pocket atoms / specific pocket"
            p.core_note = "Alpha-sphere geometry was unavailable or did not align with this loaded structure; showing pocket atoms instead."
        else:
            p.core_points = residue_core_points
            p.core_geometry = "none"
            p.core_button_label = "No pocket geometry"
            p.core_layer_label = "No pocket-specific geometry available"
            p.core_note = "No alpha-sphere or residue-position data is available for this pocket; this layer just highlights the same residue selection as \"Nearby residues\"."

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
        p.geometric_center = _pocket_center(p.core_points)
        p.residues = []
        # Bare residue numbers, kept separate from the display-formatted
        # p.residues ("Asp123") -- ngl_pocket_representations.js joins this
        # list straight into an NGL selection string ("123 OR 145 OR ..."),
        # which only understands plain residue numbers, not amino-acid-coded
        # labels.
        p.residue_ids = []
        p.comparison_residues = []
        data = []

        for rsr in p.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p.name, "id": p.name})
            p.residues.append(_residue_display_label(rsr.residue))
            p.residue_ids.append(rsr.residue.resid)
            p.comparison_residues.append(rsr.residue)
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

    for p2 in context["p2_pockets"]:
        p2.p2score = [x.value for x in p2.properties.all() if x.property == p2s][0]
        p2.probability = [x.value for x in p2.properties.all() if x.property == p2p][0]
        p2.atoms = []
        p2.core_atoms = _residue_set_core_atoms(p2)
        p2.core_points = _residue_set_core_points(p2)
        if p2.core_points:
            p2.core_geometry = "residue_atoms"
            p2.core_button_label = "Predicted site atoms"
            p2.core_layer_label = "Predicted site atoms / pocket residues"
            p2.core_note = "P2Rank reports predicted binding-site residues, not alpha-sphere geometry, so this shows the residue atoms rather than a cavity-shape mesh."
        else:
            p2.core_geometry = "none"
            p2.core_button_label = "No pocket geometry"
            p2.core_layer_label = "No pocket-specific geometry available"
            p2.core_note = "No residue-position data is available for this predicted site; this layer just highlights the same residue selection as \"Nearby residues\"."
        p2.geometric_center = _pocket_center(p2.core_points)
        p2.residues = []
        # See p.residue_ids above -- same reason, same fix.
        p2.residue_ids = []
        p2.comparison_residues = []
        data = []

        for rsr in p2.residue_set_residue.all():
            data.append({"x": rsr.residue.resid,
                         "y": rsr.residue.resid,
                         "description": p2.name, "id": p2.name})
            p2.residues.append(_residue_display_label(rsr.residue))
            p2.residue_ids.append(rsr.residue.resid)
            p2.comparison_residues.append(rsr.residue)
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

    rss = PDBResidueSet.objects.prefetch_related(
        "properties__property",
        "residue_set_residue__residue").filter(
        Q(pdb=pdbobj) &
        (~Q(residue_set__name="FPocketPocket")) &
        (~Q(residue_set__name="P2RankPocket")))
    context["residuesets"] = []
    for rs_obj in rss:
        context["residuesets"].append({"rs_name": rs_obj.residue_set.name,
                                       "name": rs_obj.name,
                                       "description": rs_obj.description,
                                       "residues": [x.residue.resid
                                                    for x in rs_obj.residue_set_residue.all()],
                                       "center": _pocket_center(_residue_set_core_points(rs_obj))})
        gf = {
            "data": [{"x": x.residue.resid, "y": x.residue.resid}
                     for x in rs_obj.residue_set_residue.all()],
            "name": "P2Rank",
            "className": "test3",
            "color": generar_color_aleatorio(),
            "type": "rect",
            "filter": "type2"
        }
        graphic_features.append(gf)
    context["pdbid"] = pdbobj.code.lower()
    for residue_set in context["residuesets"]:
        residue_set["display_label"] = _annotated_site_label(residue_set)
    context["residuesets"] = sorted(
        context["residuesets"],
        key=lambda item: (item["rs_name"], item["name"]),
    )

    # Derived pocket properties (geometric center, FPocket/P2Rank consensus, nearest
    # annotated functional site) -- computed here, after every pocket/site geometric
    # center is known, and appended to the same inspector_properties summary string
    # the sidebar already renders per pocket.
    fpocket_centers = [(f"FPocket {p.name}", p.geometric_center) for p in context["pockets"]]
    p2_centers = [(f"P2Rank {p2.name}", p2.geometric_center) for p2 in context["p2_pockets"]]
    site_centers = [
        (rs_dict["display_label"], rs_dict["center"])
        for rs_dict in context["residuesets"]
        if rs_dict.get("center")
    ]

    for p in context["pockets"]:
        consensus = _nearest_named_center(p.geometric_center, p2_centers)
        p.consensus_label = ""
        p.consensus_distance = None
        p.consensus_shared_residues = 0
        p.consensus_smaller_coverage = 0.0
        p.consensus_jaccard = 0.0
        if consensus and consensus[1] <= _POCKET_CONSENSUS_DISTANCE:
            matching_p2 = next(
                (
                    candidate
                    for candidate in context["p2_pockets"]
                    if f"P2Rank {candidate.name}" == consensus[0]
                ),
                None,
            )
            p.consensus_label = consensus[0]
            p.consensus_distance = round(consensus[1], 1)
            if matching_p2 is not None:
                overlap = _pocket_residue_overlap(
                    p.comparison_residues,
                    matching_p2.comparison_residues,
                )
                p.consensus_shared_residues = overlap["shared_count"]
                p.consensus_smaller_coverage = round(overlap["smaller_coverage"])
                p.consensus_jaccard = round(overlap["jaccard"])
        consensus_note = (
            f"Same-site prediction: {p.consensus_label} ({p.consensus_distance:.1f} Å center distance, "
            f"{p.consensus_shared_residues} shared residues, "
            f"{p.consensus_smaller_coverage:.0f}% of the smaller site)"
            if p.consensus_label else ""
        )
        nearest_site = _nearest_named_center(p.geometric_center, site_centers)
        site_note = f"Nearest annotated site: {nearest_site[0]} (Δ {nearest_site[1]:.1f} Å)" if nearest_site else ""
        p.inspector_properties = _join_nonempty([
            _inspector_property_summary(p, _FPOCKET_INSPECTOR_PROPERTIES),
            _format_pocket_center(p.geometric_center),
            consensus_note,
            site_note,
        ])

    for p2 in context["p2_pockets"]:
        consensus = _nearest_named_center(p2.geometric_center, fpocket_centers)
        p2.consensus_label = ""
        p2.consensus_distance = None
        p2.consensus_shared_residues = 0
        p2.consensus_smaller_coverage = 0.0
        p2.consensus_jaccard = 0.0
        if consensus and consensus[1] <= _POCKET_CONSENSUS_DISTANCE:
            matching_fpocket = next(
                (
                    candidate
                    for candidate in context["pockets"]
                    if f"FPocket {candidate.name}" == consensus[0]
                ),
                None,
            )
            p2.consensus_label = consensus[0]
            p2.consensus_distance = round(consensus[1], 1)
            if matching_fpocket is not None:
                overlap = _pocket_residue_overlap(
                    p2.comparison_residues,
                    matching_fpocket.comparison_residues,
                )
                p2.consensus_shared_residues = overlap["shared_count"]
                p2.consensus_smaller_coverage = round(overlap["smaller_coverage"])
                p2.consensus_jaccard = round(overlap["jaccard"])
        consensus_note = (
            f"Same-site prediction: {p2.consensus_label} ({p2.consensus_distance:.1f} Å center distance, "
            f"{p2.consensus_shared_residues} shared residues, "
            f"{p2.consensus_smaller_coverage:.0f}% of the smaller site)"
            if p2.consensus_label else ""
        )
        nearest_site = _nearest_named_center(p2.geometric_center, site_centers)
        site_note = f"Nearest annotated site: {nearest_site[0]} (Δ {nearest_site[1]:.1f} Å)" if nearest_site else ""
        p2.inspector_properties = _join_nonempty([
            _inspector_property_summary(p2, _P2RANK_INSPECTOR_PROPERTIES),
            _format_pocket_center(p2.geometric_center),
            consensus_note,
            site_note,
        ])

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

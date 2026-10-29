from django.views import View
from django.http import Http404

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB

import io
import zipfile
from tpweb.services.structure_summary import pdb_structure
from django.utils.encoding import smart_str
from tpweb.services.genome_workspace import user_can_access_genome_name
from tpweb.services.structure_downloads import (
    DOWNLOAD_SOURCE_ALL,
    DOWNLOAD_SOURCE_FOLDERS,
    build_structures_zip,
    link_genome_name,
    structure_pymol_script,
    with_pocket_pseudo_atoms,
)
from tpweb.services.structure_files import (
    display_code,
    read_structure_text,
    structure_file_path,
)


def _attachment(payload, content_type, filename):
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = f"attachment; filename={smart_str(filename)}"
    response["Content-Length"] = str(len(payload))
    return response


class StructureExportView(View):
    """VMD bundle (.pdb + .tcl) by default; ?format=pymol returns a
    self-contained PyMOL script instead."""

    def get(self, request, struct_id, *args, **kwargs):
        pdb = PDB.objects.filter(id=struct_id).first()
        if pdb is None:
            return HttpResponseNotFound()
        link = self._resolve_link(request, pdb)
        if link is None:
            return HttpResponseNotFound("No linked protein found for this structure.")
        be = link.bioentry
        biodb = link_genome_name(link)
        if not user_can_access_genome_name(request.user, biodb):
            raise Http404("Structure not found")

        if request.GET.get("format") == "pymol":
            try:
                script = structure_pymol_script(link)
            except (FileNotFoundError, OSError):
                return HttpResponseNotFound("Structure source file not found.")
            filename = f"{be.accession}_{display_code(pdb.code)}.pml"
            return _attachment(script.encode("utf-8"), "text/plain; charset=utf-8", filename)

        try:
            raw_structure_path = structure_file_path(biodb, be.accession, pdb.code)
            data = read_structure_text(raw_structure_path)
        except (FileNotFoundError, OSError):
            return HttpResponseNotFound("Structure source file not found.")
        pdb_dto = pdb_structure(pdb, [])
        pockets = pdb_dto["pockets"]
        vmd_txt = vmd_style(pockets)
        data = _with_pocket_pseudo_atoms(data, pdb, pockets)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{pdb.code}.tcl", vmd_txt)
            zip_file.writestr(f"{pdb.code}.pdb", data)
        return _attachment(stream.getvalue(), "application/zip", be.accession + ".zip")

    @staticmethod
    def _resolve_link(request, pdb):
        from tpweb.services.shared_sequence_evidence import shared_structure_link

        links = BioentryStructure.objects.select_related("bioentry__biodatabase").filter(pdb=pdb)
        requested_protein_id = str(request.GET.get("protein_id") or "").strip()
        if requested_protein_id.isdigit():
            return shared_structure_link(request.user, int(requested_protein_id), pdb.pk)
        return links.first()


class ProteinStructuresExportView(View):
    """Every structure of one protein (?source=experimental|alphafold|
    colabfold|all) with its pockets TSV and PyMOL script, as one ZIP."""

    def get(self, request, protein_id, *args, **kwargs):
        protein = (
            Bioentry.objects.select_related("biodatabase").filter(bioentry_id=protein_id).first()
        )
        if protein is None or not protein.biodatabase.name.endswith(Biodatabase.PROT_POSTFIX):
            raise Http404("Protein not found")
        genome_name = protein.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
        if not user_can_access_genome_name(request.user, genome_name):
            raise Http404("Protein not found")

        from tpweb.services.shared_sequence_evidence import apply_shared_sequence_evidence

        apply_shared_sequence_evidence([protein], request.user)

        source = request.GET.get("source") or DOWNLOAD_SOURCE_ALL
        if source != DOWNLOAD_SOURCE_ALL and source not in DOWNLOAD_SOURCE_FOLDERS:
            raise Http404("Unknown structure source")
        payload, written = build_structures_zip(protein, source)
        if not written:
            return HttpResponseNotFound("No structure files available for this selection.")
        suffix = "" if source == DOWNLOAD_SOURCE_ALL else f"_{DOWNLOAD_SOURCE_FOLDERS[source]}"
        return _attachment(
            payload, "application/zip", f"{protein.accession}_structures{suffix}.zip"
        )


def _with_pocket_pseudo_atoms(pdb_text, pdb, pockets):
    """VMD selections in vmd_style() target "resname STP" (FPocket alpha
    spheres); see structure_downloads.with_pocket_pseudo_atoms."""
    return with_pocket_pseudo_atoms(pdb_text, pdb, [p.name for p in pockets])


def vmd_style(pockets):
    """str_variants = " or ".join([ "(" + ("chain " + x.split("_")[1] + "
    // and " if x.split("_")[1].strip() else "") + "resid " +
    // x.split("_")[2] + ")" for x in variant_list if x])"""

    tcl = """set id [[atomselect 0 "protein"] molid]
mol delrep 0 $id
mol representation "NewRibbons"
mol material "Opaque"
mol color Chain
mol selection "protein"
mol addrep $id

mol representation "VDW"
mol color Element
mol selection "not protein and not resname HOH and not resname STP"
mol addrep $id
"""

    for p in list(pockets):
        rep = f"""mol representation "VDW"
mol color Element
mol selection "resname  STP and resid  {p.name}"
mol addrep $id

        """
        """mol representation "Bonds"
        mol color Element
        mol selection " index {" ".join([str(x) for x in p.atoms])} "
        mol addrep $id"""
        tcl = tcl + rep

    return tcl

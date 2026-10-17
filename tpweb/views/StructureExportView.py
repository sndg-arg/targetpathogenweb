from django.views import View
from django.http import Http404

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from tpweb.models.pdb import PDB, Residue

import gzip
import zipfile
from tpweb.services.structure_summary import pdb_structure
import io
from django.utils.encoding import smart_str
from tpweb.services.genome_workspace import user_can_access_genome_name
from tpweb.services.structure_files import structure_file_path


class StructureExportView(View):
    def get(self, request, struct_id, *args, **kwargs):
        pdbqs = PDB.objects.filter(id=struct_id)

        if pdbqs.exists():
            pdb = pdbqs.get()
            sequence_links = pdb.sequences.select_related("bioentry__biodatabase").all()
            if not sequence_links:
                return HttpResponseNotFound("No linked protein found for this structure.")
            be = sequence_links[0].bioentry
            biodb = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
            if not user_can_access_genome_name(request.user, biodb):
                raise Http404("Structure not found")
            try:
                raw_structure_path = structure_file_path(biodb, be.accession, pdb.code)
                data = gzip.open(raw_structure_path, "rt").read()
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
            payload = stream.getvalue()
            response = HttpResponse(payload, content_type="application/zip")
            response["Content-Disposition"] = (
                f"attachment; filename={smart_str(be.accession + '.zip')}"
            )
            response["Content-Length"] = str(len(payload))

            return response
        else:
            return HttpResponseNotFound()


def _with_pocket_pseudo_atoms(pdb_text, pdb, pockets):
    """vmd_style() below writes VMD selections against "resname STP" --
    FPocket's alpha-sphere pseudo-atoms -- but those only ever get stored
    in the DB (see tpweb.io.FPocket2SQL), never written into the raw
    structure file on disk that `pdb_text` comes from. Without them here,
    every pocket selection in the exported .tcl script matches zero atoms
    and the pocket spheres never show up in VMD. Re-serialize them with
    the existing Residue.lines()/Atom.line() formatters (already
    special-cased for resname "STP") and splice them in just before the
    terminating END record, so the exported .pdb actually has something
    for the script to select.
    """
    pocket_resids = []
    for p in pockets:
        try:
            pocket_resids.append(int(p.name))
        except (TypeError, ValueError):
            pass
    if not pocket_resids:
        return pdb_text

    pocket_lines = []
    for residue in Residue.objects.prefetch_related("atoms").filter(
        pdb=pdb, resname="STP", resid__in=pocket_resids
    ):
        pocket_lines += residue.lines()
    if not pocket_lines:
        return pdb_text

    lines = pdb_text.splitlines()
    insert_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].rstrip() == "END":
            insert_at = i
            break
    lines[insert_at:insert_at] = pocket_lines
    return "\n".join(lines) + "\n"


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

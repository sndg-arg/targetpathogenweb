from django.views import View
from django.conf import settings
from django.http import Http404

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from tpweb.models.pdb import PDB

import gzip
import zipfile
from tpweb.views.StructureView import pdb_structure
import io
from django.utils.encoding import smart_str
from tpweb.services.genome_workspace import user_can_access_genome_name

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
            ss = SeqStore(settings.SEQS_DATA_DIR)
            try:
                data = gzip.open(ss.structure(biodb, be.accession, pdb.code), "rt").read()
            except (FileNotFoundError, OSError):
                return HttpResponseNotFound("Structure source file not found.")
            pdb_dto = pdb_structure(pdb, [])
            vmd_txt = vmd_style(pdb_dto["pockets"])
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr(f'{pdb.code}.tcl', vmd_txt)
                zip_file.writestr(f'{pdb.code}.pdb', data)
            payload = stream.getvalue()
            response = HttpResponse(payload, content_type="application/zip")
            response["Content-Disposition"] = "attachment; filename=%s" % smart_str(be.accession + ".zip")
            response["Content-Length"] = str(len(payload))

            return response
        else:
            return HttpResponseNotFound()


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

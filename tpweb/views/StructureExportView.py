from django.views import View
from django.conf import settings

from django.http import HttpResponse, HttpResponseNotFound

from bioseq.io.BioIO import BioIO
from bioseq.io.SeqStore import SeqStore
from tpweb.models.pdb import PDB

import gzip
import zipfile
from tpweb.views.StructureView import pdb_structure
import io
from django.utils.encoding import smart_str

class StructureExportView(View):

    def get(self, request, struct_id, *args, **kwargs):
        pdbqs = PDB.objects.filter(id=struct_id)

        if pdbqs.exists():
            pdb = pdbqs.get()
            be = pdb.sequences.all()[0].bioentry
            biodb = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
            ss = SeqStore(settings.SEQS_DATA_DIR)
            data = gzip.open(ss.structure(biodb, be.accession, pdb.code),"rt").read()
            pdb_dto = pdb_structure(pdb, [])
            vmd_txt = vmd_style(pdb_dto["pockets"])
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, mode='w') as zip_file:
                zip_file.writestr(f'{pdb.code}.tcl', vmd_txt)
                zip_file.writestr(f'{pdb.code}.pdb', data)
            stream.seek(0)


            response = HttpResponse(stream, content_type='application/force-download')
            response['Content-Disposition'] = 'attachment; filename=%s' % smart_str(be.accession + ".zip")

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

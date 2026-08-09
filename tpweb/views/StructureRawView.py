import logging

from django.http import Http404, HttpResponse, HttpResponseNotFound
from django.views import View

from bioseq.io.BioIO import BioIO
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB
from tpweb.services.genome_workspace import user_can_access_genome_name
from tpweb.services.structure_files import detect_structure_format, read_structure_text, structure_file_path

logger = logging.getLogger(__name__)


class StructureRawView(View):
    template_name = "genomic/protein.html"

    def get(self, request, struct_id, *args, **kwargs):
        pdbqs = PDB.objects.filter(id=struct_id)

        if pdbqs.exists():
            pdb = pdbqs.get()
            be = self._resolve_source_bioentry(request, pdb)
            if be is None:
                raise Http404("Structure not found")
            biodb = be.biodatabase.name.replace(BioIO.GENOME_PROT_POSTFIX, "")
            if not user_can_access_genome_name(request.user, biodb):
                raise Http404("Structure not found")
            try:
                raw_structure_path = structure_file_path(biodb, be.accession, pdb.code)
                structure_format = detect_structure_format(raw_structure_path)
                data = read_structure_text(raw_structure_path)
            except (FileNotFoundError, OSError) as exc:
                logger.warning(
                    "Structure source file not found: struct_id=%s pdb_code=%s bioentry_id=%s genome=%s (%s)",
                    struct_id, pdb.code, be.bioentry_id, biodb, exc,
                )
                return HttpResponseNotFound("Structure source file not found.")

            content_type = (
                "chemical/x-cif; charset=utf-8"
                if structure_format == "cif"
                else "chemical/x-pdb; charset=utf-8"
            )
            response = HttpResponse(data, content_type=content_type)
            response["X-Structure-Format"] = structure_format
            return response
        return HttpResponseNotFound()

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

from django.shortcuts import render
from django.http import Http404
from django.views import View
from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.models.pdb import PDB
from tpweb.services.genome_workspace import user_can_access_genome_name, genome_url_slug
from tpweb.services.structure_files import (
    detect_structure_format,
    disambiguate_display_codes,
    display_code,
    structure_file_path,
)
from tpweb.services.structure_sources import (
    chain_selector as _chain_selector,
    is_multichain as _is_multichain,
)
from tpweb.services.structure_summary import pdb_structure


_SHORT_METHOD = {"EX": "Crystal", "AF": "AlphaFold DB", "CF": "ColabFold"}


class StructureView(View):
    template_name = "genomic/structure.html"

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
                BioentryStructure.objects.select_related("pdb")
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
                s_data = (
                    primary_data
                    if pdb.id == structure.id
                    else pdb_structure(pdb, [], target_chain=link_chain or None)
                )
                exp = (pdb.experiment or "").upper()
                multichain = _is_multichain(link.chain, s_data)
                all_structures.append(
                    {
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
                    }
                )

            # Ensure the requested structure is always in the list
            if not any(s["id"] == structure.id for s in all_structures):
                primary_chain_value = primary_link.chain if primary_link else ""
                chain_sel = _chain_selector(primary_chain_value)
                exp = (structure.experiment or "").upper()
                multichain = _is_multichain(primary_chain_value, primary_data)
                all_structures.insert(
                    0,
                    {
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
                    },
                )

            disambiguate_display_codes(all_structures)
            dto["all_structures"] = all_structures
            active = next(
                (s for s in all_structures if s["is_active"]),
                all_structures[0] if all_structures else None,
            )
            if active:
                dto["viewer_chain_selector"] = active["chain_selector"]
        else:
            exp = (structure.experiment or "").upper()
            multichain = _is_multichain("", primary_data)
            dto["all_structures"] = [
                {
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
                }
            ]
            dto["viewer_chain_selector"] = "polymer"

        return render(request, self.template_name, dto)

    @staticmethod
    def _structure_file_format(source_bioentry, structure):
        if source_bioentry is None:
            source_link = (
                BioentryStructure.objects.select_related("bioentry__biodatabase")
                .filter(pdb=structure)
                .first()
            )
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
            link = (
                BioentryStructure.objects.select_related("bioentry__biodatabase")
                .filter(pdb=structure, bioentry_id=int(requested_protein_id))
                .first()
            )
            if link and link.bioentry:
                return link.bioentry

        first_link = (
            BioentryStructure.objects.select_related("bioentry__biodatabase")
            .filter(pdb=structure)
            .first()
        )
        if first_link and first_link.bioentry:
            return first_link.bioentry
        return None

    @staticmethod
    def _resolve_source_assembly_name(source_bioentry):
        biodb_name = getattr(getattr(source_bioentry, "biodatabase", None), "name", "") or ""
        prot_postfix = getattr(Biodatabase, "PROT_POSTFIX", "")
        if prot_postfix and biodb_name.endswith(prot_postfix):
            return biodb_name[: -len(prot_postfix)]
        if prot_postfix:
            return biodb_name.replace(prot_postfix, "")
        return biodb_name

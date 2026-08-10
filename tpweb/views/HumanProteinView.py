from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from tpweb.services.binder_summary import create_binders_dict
from tpweb.services.human_protein_summary import (
    build_human_function_context,
    build_human_overview_context,
    build_human_sequence_context,
    build_human_xref_context,
)
from tpweb.services.human_structure_summary import build_human_structure_context
from tpweb.services.human_targets import get_human_bioentry
from tpweb.services.protein_annotations import iter_protein_annotations


class HumanProteinView(View):
    template_name = "human/human_protein.html"

    def get(self, request, accession, *args, **kwargs):
        bioentry = get_human_bioentry(accession)
        human_protein = getattr(bioentry, "human_protein", None) if bioentry else None
        if bioentry is None or human_protein is None:
            raise Http404("Human protein not found")

        structures = list(bioentry.structures.select_related("pdb").all())
        binders_search_query = request.GET.get("binder_search", "").strip()
        binders = create_binders_dict(
            bioentry, search_query=binders_search_query, structures=structures
        )

        context = {
            "bioentry": bioentry,
            "human_protein": human_protein,
            # Minimal dict exposing `.id` = bioentry pk, matching the shape
            # the shared `components/binders/table_*.html` partials expect
            # (they read `protein.id` for the "Open crystal" structure-viewer
            # link) -- mirrors ProteinView's `proteinDTO["id"]` convention.
            "protein": {"id": bioentry.bioentry_id},
            "accession": human_protein.uniprot_accession,
            "overview": build_human_overview_context(human_protein),
            "function": build_human_function_context(human_protein),
            "sequence": build_human_sequence_context(human_protein),
            "xrefs": build_human_xref_context(human_protein),
            "structure": build_human_structure_context(bioentry),
            "binders": binders,
            "ec_badges": list(iter_protein_annotations(bioentry, "ec"))[:6],
            "go_badges": list(iter_protein_annotations(bioentry, "go"))[:6],
            "human_protein_list_url": reverse("tpwebapp:human_protein_list"),
        }
        return render(request, self.template_name, context)

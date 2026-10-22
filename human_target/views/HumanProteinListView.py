from urllib.parse import urlencode

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.views import View

from human_target.services.human_dashboard_summary import build_human_dashboard_context
from human_target.services.human_targets import human_proteins_queryset
from tpweb.models.Binders import Binders
from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.services.structure_sources import summarize_structure_sources
from tpweb.views.ProteinListView import ProteinListView
from tpweb.views.mixins import PermissionLockedMixin

PAGE_SIZE = 40


def _table_rows(proteins):
    """One row per protein on this page, with the same Structure and ligand
    columns as the pathogen protein table (queried for this page only)."""
    bioentry_ids = [hp.bioentry_id for hp in proteins]
    structures = {}
    for link in BioentryStructure.objects.filter(bioentry_id__in=bioentry_ids).select_related(
        "pdb"
    ):
        structures.setdefault(link.bioentry_id, []).append(link)
    ligands = {
        row["locustag__bioentry_id"]: row
        for row in Binders.objects.filter(locustag__bioentry_id__in=bioentry_ids)
        .values("locustag__bioentry_id")
        .annotate(total=Count("id"), direct=Count("id", filter=Q(is_direct=True)))
    }
    return [
        {
            "protein": hp,
            "structure": summarize_structure_sources(structures.get(hp.bioentry_id, [])),
            "ligands": ligands.get(hp.bioentry_id, {"total": 0, "direct": 0}),
        }
        for hp in proteins
    ]


class HumanProteinListView(PermissionLockedMixin, View):
    template_name = "human/human_protein_list.html"
    page_title = "Human Targets"
    locked_message = "Human Targets is available to project collaborators."

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_human_targets")

    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()
        # DB-side filter + pagination -- the old implementation materialized
        # every HumanProtein (every JSON field included) into a Python list
        # before filtering, fine at the 10-protein pilot scale, not at the
        # full ~20,400-protein proteome.
        proteins_qs = human_proteins_queryset(query).order_by("uniprot_accession")
        total_count = proteins_qs.count()

        paginator = Paginator(proteins_qs, PAGE_SIZE)
        try:
            page = paginator.page(request.GET.get("page"))
        except PageNotAnInteger:
            page = paginator.page(1)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        return render(
            request,
            self.template_name,
            {
                "proteins": page,
                "rows": _table_rows(list(page.object_list)),
                "page_numbers": ProteinListView._build_page_numbers(
                    page.number, paginator.num_pages
                ),
                "query_string": urlencode({"q": query}) if query else "",
                "total_count": total_count,
                "all_count": human_proteins_queryset().count() if query else total_count,
                "query": query,
                "dashboard": build_human_dashboard_context(),
            },
        )

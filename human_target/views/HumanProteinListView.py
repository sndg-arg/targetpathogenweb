from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render
from django.views import View

from human_target.services.human_dashboard_summary import build_human_dashboard_context
from human_target.services.human_targets import human_proteins_queryset
from tpweb.views.mixins import PermissionLockedMixin

PAGE_SIZE = 40


class HumanProteinListView(PermissionLockedMixin, View):
    template_name = "human/human_protein_list.html"
    page_title = "Human Targets"
    locked_message = (
        "Human Targets is available to project collaborators. Ask a site administrator for access."
    )

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_human_targets")

    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()
        # DB-side filter + pagination -- the old implementation materialized
        # every HumanProtein (every JSON field included) into a Python list
        # before filtering, fine at the 10-protein pilot scale, not at the
        # full ~20,400-protein proteome.
        proteins_qs = human_proteins_queryset(query)
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
                "total_count": total_count,
                "query": query,
                "dashboard": build_human_dashboard_context(),
            },
        )

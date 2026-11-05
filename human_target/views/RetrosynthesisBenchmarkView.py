from django.shortcuts import render
from django.views import View

from human_target.services.retrosynthesis_benchmark import build_benchmark_context
from tpweb.views.mixins import PermissionLockedMixin


class RetrosynthesisBenchmarkView(PermissionLockedMixin, View):
    template_name = "human/retrosynthesis_benchmark.html"
    page_title = "Retrosynthesis benchmark"
    locked_message = "Human Targets is available to project collaborators."

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_human_targets")

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"benchmark": build_benchmark_context()})

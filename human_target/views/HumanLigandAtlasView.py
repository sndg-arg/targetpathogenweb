from django.shortcuts import render
from django.views import View

from human_target.services.human_ligand_atlas import build_ligand_atlas_context
from tpweb.views.mixins import PermissionLockedMixin


class HumanLigandAtlasView(PermissionLockedMixin, View):
    template_name = "human/human_ligand_atlas.html"
    page_title = "Ligand coverage"
    locked_message = "Human Targets is available to project collaborators."

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_human_targets")

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"atlas": build_ligand_atlas_context()})

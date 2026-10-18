from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.views import View

from tpweb.views.mixins import PermissionLockedMixin


class DesignSystemView(PermissionLockedMixin, View):
    """Showcase of the site's look (/design): colors, type and the real
    components, rendered with the site's own CSS so it never drifts. Shown at
    project stands, so it's limited to Gates collaborators, admins and the
    owner (superusers). Not linked from the nav or the sitemap."""

    template_name = "about/design_system.html"
    page_title = "Design"
    locked_message = "This page is for Gates collaborators and administrators."

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.role == get_user_model().Role.GATES_COLLABORATOR

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

from django.shortcuts import render
from django.views import View


class DesignSystemView(View):
    """Unlisted visual reference (/design): colors, type, spacing, buttons
    and components, rendered with the site's own CSS so it never drifts.
    Not linked from the nav or the sitemap; reachable by URL only."""

    template_name = "about/design_system.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

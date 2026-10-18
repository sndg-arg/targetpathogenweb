from django.shortcuts import render
from django.views import View


class DesignSystemView(View):
    """Showcase of the site's look (/design): colors, type and the real
    components, rendered with the site's own CSS so it never drifts. Open to
    anyone with the link (it's shared at project stands); only Gates
    collaborators, admins and the owner see it in their profile menu."""

    template_name = "about/design_system.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

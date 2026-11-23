from django.shortcuts import render
from django.views import View

from tpweb.services.topology_diagram import build_topology_diagram

# A three-pass membrane protein, N terminus outside, for the Cell diagram row.
_SAMPLE_TOPOLOGY = [
    {"start": 1, "end": 20, "kind": "outside"},
    {"start": 21, "end": 43, "kind": "membrane"},
    {"start": 70, "end": 92, "kind": "membrane"},
    {"start": 160, "end": 182, "kind": "membrane"},
]


class DesignSystemView(View):
    """Showcase of the site's look (/design): colors, type and the real
    components, rendered with the site's own CSS so it never drifts. Open to
    anyone with the link (it's shared at project stands); only Gates
    collaborators, admins and the owner see it in their profile menu."""

    template_name = "about/design_system.html"

    def get(self, request, *args, **kwargs):
        topology = build_topology_diagram(_SAMPLE_TOPOLOGY, 240, "Extracellular", "Cytoplasm")
        return render(request, self.template_name, {"sample_topology": topology})

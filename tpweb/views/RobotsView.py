from django.http import HttpResponse
from django.views import View

ROBOTS_TXT = """User-agent: GPTBot
Disallow: /

Sitemap: https://target2.infra.cluster.qb.fcen.uba.ar/sitemap.xml
"""


class RobotsView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse(ROBOTS_TXT, content_type="text/plain")

from django.http import HttpResponse
from django.views import View

ROBOTS_TXT = """User-agent: GPTBot
Disallow: /
"""


class RobotsView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse(ROBOTS_TXT, content_type="text/plain")

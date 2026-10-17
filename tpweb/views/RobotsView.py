from django.http import HttpResponse
from django.views import View

# The whole site sits behind a login wall (see
# tpweb/middleware/access_control.py) -- nothing here is reachable
# anonymously regardless of what a crawler does, so every user-agent gets
# the same "don't bother" rather than singling out GPTBot.
ROBOTS_TXT = """User-agent: *
Disallow: /
"""


class RobotsView(View):
    def get(self, request, *args, **kwargs):
        return HttpResponse(ROBOTS_TXT, content_type="text/plain")

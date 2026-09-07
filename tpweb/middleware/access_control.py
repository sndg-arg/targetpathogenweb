from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from tpweb.middleware.observability import _first_forwarded_ip
from tpweb.services.ip_blocking import is_ip_blocked


EXEMPT_PATH_PREFIXES = (
    "/accounts/",
    "/health/live",
    "/health/ready",
    "/health/pipeline",
    # A crawler requesting this politely (as GPTBot etc. does before
    # touching anything else) should get the real "stay out" directive, not
    # a login redirect it can't follow -- gating it just meant bots kept
    # probing the rest of the site instead of backing off after reading it.
    "/robots.txt",
)


class LoginRequiredMiddleware:
    """Gate every request behind login by default.

    New views are private unless explicitly added to EXEMPT_PATH_PREFIXES --
    safer than decorating each view individually, which is easy to forget.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated or self._is_exempt(request.path):
            return self.get_response(request)
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

    def _is_exempt(self, path):
        if path.startswith(settings.STATIC_URL):
            return True
        return path.startswith(EXEMPT_PATH_PREFIXES)


class BlockedIPMiddleware:
    """Deny an explicitly blocked IP outright (403), no exemptions -- unlike
    LoginRequiredMiddleware's redirect, this also covers /accounts/login and
    /robots.txt, since the whole point of blocking one is to stop it from
    reaching anything at all.

    Placed ahead of LoginRequiredMiddleware in settings.MIDDLEWARE so a
    blocked IP never even reaches the login-wall check.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        real_ip = request.META.get("HTTP_X_REAL_IP", "")
        remote_addr = request.META.get("REMOTE_ADDR", "")
        client_ip = _first_forwarded_ip(forwarded_for) or real_ip or remote_addr
        if is_ip_blocked(client_ip):
            return HttpResponseForbidden("Forbidden")
        return self.get_response(request)

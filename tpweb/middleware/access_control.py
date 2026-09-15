from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from tpweb.middleware.observability import _first_forwarded_ip
from tpweb.services.bot_detection import AUTO_BLOCK_BOT_LABELS, classify_bot
from tpweb.services.ip_blocking import block_ip, is_ip_blocked


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


def _is_exempt_path(path):
    if path.startswith(settings.STATIC_URL):
        return True
    return path.startswith(EXEMPT_PATH_PREFIXES)


def _resolve_client_ip(request):
    # X-Forwarded-For is set by Traefik; REMOTE_ADDR alone would just be the
    # proxy's own IP. Take the first hop (the original client) since a
    # comma-separated chain means the request passed through more than one
    # proxy. Same resolution RequestTimingMiddleware uses for RequestLog.ip.
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    real_ip = request.META.get("HTTP_X_REAL_IP", "")
    remote_addr = request.META.get("REMOTE_ADDR", "")
    return _first_forwarded_ip(forwarded_for) or real_ip or remote_addr


class LoginRequiredMiddleware:
    """Gate every request behind login by default.

    New views are private unless explicitly added to EXEMPT_PATH_PREFIXES --
    safer than decorating each view individually, which is easy to forget.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated or _is_exempt_path(request.path):
            return self.get_response(request)
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)


class BlockedIPMiddleware:
    """Deny an explicitly blocked IP outright (403), no exemptions -- unlike
    LoginRequiredMiddleware's redirect, this also covers /accounts/login and
    /robots.txt, since the whole point of blocking one is to stop it from
    reaching anything at all.

    Also auto-blocks on first sight: an anonymous request to a non-exempt
    path from a User-Agent classified as AUTO_BLOCK_BOT_LABELS (AI crawler /
    generic bot -- see tpweb.services.bot_detection) gets blocked right then,
    no staff action needed. A bot that only ever requests robots.txt is
    behaving exactly as asked and is left alone; one that touches anything
    else gets cut off immediately and permanently (see BlockedIP).

    Placed ahead of LoginRequiredMiddleware in settings.MIDDLEWARE so a
    blocked IP never even reaches the login-wall check.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_ip = _resolve_client_ip(request)
        if is_ip_blocked(client_ip):
            return HttpResponseForbidden("Forbidden")

        auto_block_label = self._auto_block_label(request)
        if auto_block_label:
            if client_ip:
                block_ip(client_ip, reason=f"auto: {auto_block_label}")
            return HttpResponseForbidden("Forbidden")

        return self.get_response(request)

    def _auto_block_label(self, request):
        if request.user.is_authenticated or _is_exempt_path(request.path):
            return None
        label = classify_bot(request.META.get("HTTP_USER_AGENT", ""))
        return label if label in AUTO_BLOCK_BOT_LABELS else None

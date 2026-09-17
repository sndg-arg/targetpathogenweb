from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.urls import Resolver404, resolve

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

# Routes an anonymous "Visitor" can browse with no account at all -- exact
# url_name matches, not path prefixes: "genome/<genome>" (assembly, public)
# is a literal string-prefix of "genome/<genome>/proteins/blast",
# "genome/<genome>/formula", and "genome/<genome>/custom-evidence" (all
# still gated), so prefix matching here would be ambiguous by construction.
# Deliberately a separate list from EXEMPT_PATH_PREFIXES/_is_exempt_path --
# that one also controls BlockedIPMiddleware's bot auto-block below, and a
# bot hammering e.g. /protein/123 should still get auto-blocked exactly as
# it does today. Only the login *redirect* relaxes for these, not the bot
# defense.
PUBLIC_URL_NAMES = frozenset(
    {
        "index",
        "data_sources",
        "about_us",
        "assembly",
        "genome_metabolism",
        "genome_metabolism_network",
        "genome_metabolism_network_data",
        "genome_metabolism_network_expand",
        "genome_metabolism_pathway",
        "annotation_explorer",
        "protein",
        "protein_metabolic_network",
        "protein_metabolic_network_page",
        "protein_list",
        "protein_search_suggestions",
        "protein_advanced_filters",
        "download",
        "genomes_list",
        "molecules",
        "structure_raw",
        "structure_export",
        "load_options",
        "structure",
        "binder_detail",
        "validate_expression",
    }
)


def _is_exempt_path(path):
    if path.startswith(settings.STATIC_URL):
        return True
    return path.startswith(EXEMPT_PATH_PREFIXES)


def _is_public_view(path):
    try:
        match = resolve(path)
    except Resolver404:
        return False
    return match.url_name in PUBLIC_URL_NAMES


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

    New views are private unless explicitly added to EXEMPT_PATH_PREFIXES or
    PUBLIC_URL_NAMES -- safer than decorating each view individually, which
    is easy to forget. PUBLIC_URL_NAMES is the "Visitor" browsing allow-list
    (genomes/proteins/structures/etc.); every route that must stay gated
    (upload, formulas, custom params, BLAST, the AI assistant, /users,
    /activity, /profile) keeps its own view-level guard regardless of this
    middleware, so a mistake here degrades to "a page is visible that
    shouldn't be" rather than "a mutation endpoint is open to anyone."
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            or _is_exempt_path(request.path)
            or _is_public_view(request.path)
        ):
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

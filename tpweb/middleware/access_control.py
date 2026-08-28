from django.conf import settings
from django.contrib.auth.views import redirect_to_login


EXEMPT_PATH_PREFIXES = (
    "/accounts/",
    "/health/live",
    "/health/ready",
    "/health/pipeline",
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

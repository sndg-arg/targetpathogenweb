from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin,
    UserPassesTestMixin,
)
from django.http import JsonResponse
from django.shortcuts import render, resolve_url


class PermissionLockedMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Shared no-permission experience for gated pages -- instead of
    Django's bare 403 error page, or a page that silently renders with
    unrelated content while the one thing you came for is missing, every
    gated view shows the same unmissable "you don't have access to
    <page>" panel (components/access_locked.html). Anonymous users still
    get the normal login redirect (LoginRequiredMixin runs first, so
    test_func never even sees them); only an authenticated-but-unauthorized
    user reaches this.

    Subclasses set `page_title` (shown as the heading) and, optionally,
    `locked_message` (defaults to the generic "ask the owner" copy), and
    still implement `test_func` exactly as they would with a plain
    UserPassesTestMixin.
    """

    page_title = ""
    locked_message = "Ask the site owner to grant access."

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return render(
            self.request,
            "components/access_locked.html",
            {"page_title": self.page_title, "locked_message": self.locked_message},
            status=403,
        )


class JsonPermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """JSON-endpoint counterpart to PermissionLockedMixin -- for views only
    ever called via fetch() (the AI chat drawer, static/js/global/agent-drawer.js),
    where the client always calls response.json() regardless of status. A
    real 302 redirect would be silently followed by fetch and break that
    parsing, so an anonymous caller gets a 401 JSON body carrying login_url
    for the client to navigate to, instead of Django's own redirect_to_login.
    An authenticated caller who just lacks the permission gets a 403 JSON
    body with `locked_message`.
    """

    raise_exception = True
    locked_message = "You don't have access to this feature."

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            login_url = resolve_url(self.get_login_url())
            return JsonResponse(
                {
                    "error": "login_required",
                    "login_url": f"{login_url}?next={self.request.path}",
                },
                status=401,
            )
        return JsonResponse({"error": self.locked_message}, status=403)

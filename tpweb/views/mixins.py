from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import render


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

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from tpweb.services.user_approval import request_collaborator_access


class RequestAccessView(LoginRequiredMixin, View):
    """POST-only "Request access" button on locked pages and the profile:
    flags the account for review on /users and notifies the superusers."""

    def post(self, request, *args, **kwargs):
        next_url = self._safe_next(request)
        institution = (request.POST.get("institution") or "").strip()
        # The field is required in the form; a request that gets here
        # without one is bounced rather than silently filed, since the
        # institution is what the superusers review.
        if not institution and not request.user.collaborator_institution:
            messages.error(request, "Tell us which institution you belong to.")
            return redirect(next_url)
        if request_collaborator_access(request.user, institution=institution):
            messages.success(
                request,
                "Access requested. An administrator will review it; you'll keep "
                "using this same account.",
            )
        else:
            messages.info(request, "You already requested access; it's waiting for review.")
        return redirect(next_url)

    def _safe_next(self, request):
        next_url = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return "tpwebapp:profile"
        return next_url

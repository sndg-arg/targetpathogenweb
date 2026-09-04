from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.services.user_approval import approve_user, reject_signup, revoke_access
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME

User = get_user_model()


class UserManagementView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "users/manage.html"

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context())

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action") or "approve"
        user_id = request.POST.get("user_id")
        user = User.objects.filter(pk=user_id).exclude(username=PUBLIC_WORKSPACE_USERNAME).first()
        if user is None:
            messages.warning(request, "That account no longer exists.")
        elif action == "reject":
            username = user.get_username()
            if reject_signup(user):
                messages.success(request, f"Rejected and deleted {username}.")
            else:
                messages.error(request, "Only a still-pending account can be rejected.")
        elif action == "revoke":
            if user.is_superuser:
                messages.error(request, "Can't revoke a superuser's access here.")
            else:
                revoke_access(user)
                messages.success(request, f"Revoked access for {user.get_username()}.")
        else:
            approve_user(user)
            messages.success(request, f"Approved {user.get_username()}.")
        return redirect(reverse("tpwebapp:user_management"))

    def _context(self):
        base_qs = User.objects.exclude(username=PUBLIC_WORKSPACE_USERNAME)
        return {
            "pending_users": base_qs.filter(is_active=False).order_by("-date_joined"),
            "approved_users": base_qs.filter(is_active=True).order_by("-date_joined"),
        }

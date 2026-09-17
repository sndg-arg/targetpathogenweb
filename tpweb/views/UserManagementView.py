import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.services.user_approval import reactivate_user, reject_signup, revoke_access
from tpweb.services.user_permissions import (
    granted_codenames,
    permission_choices,
    profile_presets,
    set_user_permissions,
)
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME
from tpweb.views.mixins import PermissionLockedMixin

User = get_user_model()


class UserManagementView(PermissionLockedMixin, View):
    template_name = "users/manage.html"
    page_title = "Manage users"
    locked_message = "Only the site owner can manage user accounts."

    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context())

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action") or "reactivate"
        user_id = request.POST.get("user_id")
        user = User.objects.filter(pk=user_id).exclude(username=PUBLIC_WORKSPACE_USERNAME).first()
        if user is None:
            messages.warning(request, "That account no longer exists.")
        elif action == "reject":
            username = user.get_username()
            if reject_signup(user):
                messages.success(request, f"Deleted {username}.")
            else:
                messages.error(request, "Only a deactivated account can be deleted here.")
        elif action == "revoke":
            if user.is_superuser:
                messages.error(request, "Can't revoke a superuser's access here.")
            else:
                revoke_access(user)
                messages.success(request, f"Revoked access for {user.get_username()}.")
        elif action == "update_permissions":
            if user.is_superuser:
                messages.error(request, "Superusers already have every permission.")
            else:
                set_user_permissions(user, request.POST.getlist("permissions"))
                requested_role = request.POST.get("role")
                if requested_role in User.Role.values:
                    user.role = requested_role
                    update_fields = ["role"]
                    # A superuser assigning a real role is the resolution of
                    # the collaborator-access request -- clear the flag so
                    # the "requested" chip doesn't linger once granted.
                    if requested_role != User.Role.BASIC and user.wants_collaborator_access:
                        user.wants_collaborator_access = False
                        update_fields.append("wants_collaborator_access")
                    user.save(update_fields=update_fields)
                messages.success(request, f"Updated permissions for {user.get_username()}.")
        else:
            reactivate_user(user)
            messages.success(request, f"Reactivated {user.get_username()}.")
        return redirect(reverse("tpwebapp:user_management"))

    def _context(self):
        base_qs = User.objects.exclude(username=PUBLIC_WORKSPACE_USERNAME)
        approved_users = list(base_qs.filter(is_active=True).order_by("-date_joined"))
        # Self-serve signups now land here directly (no approval wait), so
        # this roster can get large fast -- surface anyone still waiting on
        # a collaborator-access request at the top rather than needing a
        # separate filter UI to find them. list.sort() is stable, so the
        # existing -date_joined order is preserved within each group.
        approved_users.sort(key=lambda u: not u.wants_collaborator_access)
        for approved_user in approved_users:
            # Not a model field -- attached here purely so the template can
            # drop it straight into the Edit button's data-granted attribute
            # for the JS modal to read, without a second per-row query.
            approved_user.granted_permissions_json = json.dumps(
                sorted(granted_codenames(approved_user))
            )
        return {
            "pending_users": base_qs.filter(is_active=False).order_by("-date_joined"),
            "approved_users": approved_users,
            "permission_choices": permission_choices(),
            "profile_presets": profile_presets(),
            "role_choices": User.Role.choices,
        }

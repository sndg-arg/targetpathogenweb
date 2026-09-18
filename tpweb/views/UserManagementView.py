from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.services.user_approval import reactivate_user, reject_signup, revoke_access
from tpweb.services.user_permissions import profile_presets, set_user_permissions
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME
from tpweb.views.mixins import PermissionLockedMixin

User = get_user_model()


class UserManagementView(PermissionLockedMixin, View):
    template_name = "users/manage.html"
    page_title = "Manage users"
    locked_message = "Only the site owner can manage user accounts."
    # Sentinel posted by the role <select>'s "Admin" option (manage.html) --
    # not a TPUser.Role value, see the update_permissions branch below.
    ADMIN_ROLE_VALUE = "admin"

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
            if user.is_superuser and user.is_staff:
                # The true site owner (is_staff too, set via Django admin
                # only) can't be edited here -- an Admin promoted from this
                # page (is_superuser but not is_staff) can still be picked
                # up below and moved to a real role.
                messages.error(request, "Superusers already have every permission.")
            else:
                requested_role = request.POST.get("role")
                if requested_role == self.ADMIN_ROLE_VALUE:
                    # Not a TPUser.Role value -- Admin means is_superuser,
                    # which already bypasses every has_perm() check
                    # regardless of the role field, so there's no preset
                    # codename list to apply here.
                    user.is_superuser = True
                    update_fields = ["is_superuser"]
                    if user.wants_collaborator_access:
                        user.wants_collaborator_access = False
                        update_fields.append("wants_collaborator_access")
                    user.save(update_fields=update_fields)
                    messages.success(request, f"Granted admin access to {user.get_username()}.")
                    return redirect(reverse("tpwebapp:user_management"))

                presets_by_key = {preset["key"]: preset for preset in profile_presets()}
                if requested_role in presets_by_key:
                    set_user_permissions(user, presets_by_key[requested_role]["codenames"])
                    update_fields = []
                    if user.role != requested_role:
                        user.role = requested_role
                        update_fields.append("role")
                    # Picking a real role for a promoted (non-staff) Admin
                    # is a demotion -- take the is_superuser bypass away so
                    # the role's own codenames actually take effect.
                    if user.is_superuser:
                        user.is_superuser = False
                        update_fields.append("is_superuser")
                    # A superuser assigning a role is the resolution of the
                    # collaborator-access request -- clear the flag so the
                    # "requested" chip doesn't linger once granted.
                    if requested_role != User.Role.BASIC and user.wants_collaborator_access:
                        user.wants_collaborator_access = False
                        update_fields.append("wants_collaborator_access")
                    if update_fields:
                        user.save(update_fields=update_fields)
                    messages.success(request, f"Updated permissions for {user.get_username()}.")
                else:
                    messages.error(request, "Pick a valid role.")
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
        return {
            "pending_users": base_qs.filter(is_active=False).order_by("-date_joined"),
            "approved_users": approved_users,
            "profile_presets": profile_presets(),
            "admin_role_value": self.ADMIN_ROLE_VALUE,
        }

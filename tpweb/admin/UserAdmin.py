from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from tpweb.forms.UserForms import UserAdminChangeForm, UserAdminCreationForm
from tpweb.services.user_approval import reactivate_user

User = get_user_model()


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("name", "email")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "role",
                    "wants_collaborator_access",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = [
        "username",
        "name",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "role",
        "date_joined",
    ]
    list_filter = ("is_active", "is_staff", "is_superuser", "role", "wants_collaborator_access")
    ordering = ("-date_joined",)
    search_fields = ["name", "username", "email"]
    actions = ["reactivate_selected_users"]

    @admin.action(description=_("Reactivate selected users"))
    def reactivate_selected_users(self, request, queryset):
        for user in queryset:
            reactivate_user(user)
        self.message_user(
            request, _("Reactivated %(count)d user(s).") % {"count": queryset.count()}
        )

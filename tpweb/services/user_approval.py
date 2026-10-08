"""Account activation/access workflow: self-signups activate immediately as
a Basic account (no admin review needed) -- see tpweb/adapters/
AccountAdapters.py for where signups are routed through
activate_new_signup(). A superuser elevates someone's role from
tpweb/views/UserManagementView.py's /users screen, and can revoke or
reactivate access from there or tpweb/admin/UserAdmin.py.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from tpweb.services.user_permissions import PROFILE_PRESETS

logger = logging.getLogger(__name__)

User = get_user_model()

# Every self-serve Basic signup gets these automatically -- deliberately a
# SHORT list, derived from PROFILE_PRESETS' "basic" entry (the single
# source of truth for what that role grants, also used by /users' role
# selector) rather than a second hand-maintained copy that could drift out
# of sync with it. Basic accounts activate instantly with zero human review
# now (see activate_new_signup below), so nothing that exposes gated
# content or consumes real resources belongs in that preset:
#   - can_view_restricted_genomes / can_view_human_targets: gate content
#     that's meant to stay hidden from a rando who just signed up (curated
#     research genomes, the Human Targets pilot) -- Gates-role-only, granted
#     manually per user from /users, never automatic.
#   - can_upload_genome: queues a real pipeline run (compute + storage) and
#     writes into the shared "public" workspace naming scheme -- also
#     Gates-role-only now.
#   - can_view_activity / can_curated_import: unaffected, always were
#     individually-granted only (see TPUser.Meta.permissions).
# Basic keeps just enough to be useful without an elevated role: BLAST,
# formulas, and custom params are all scoped to the user's own workspace
# (no cross-account exposure), and the AI assistant is bounded by the daily
# quota in tpweb.services.agent_chat_quota regardless of role.
#
# Only affects activations from here on -- changing this list doesn't touch
# any already-active user's existing permissions (see _grant_default_permissions).
DEFAULT_APPROVED_PERMISSION_CODENAMES = next(
    preset["codenames"] for preset in PROFILE_PRESETS if preset["key"] == "basic"
)


def _grant_default_permissions(user):
    permissions = list(
        Permission.objects.filter(
            content_type__app_label="tpweb", codename__in=DEFAULT_APPROVED_PERMISSION_CODENAMES
        )
    )
    found_codenames = {p.codename for p in permissions}
    missing = set(DEFAULT_APPROVED_PERMISSION_CODENAMES) - found_codenames
    if missing:
        # Migration 0074 hasn't run yet on this database -- shouldn't
        # happen in normal operation, but don't let missing permission
        # rows block activation itself.
        logger.warning("Permission(s) tpweb.%s not found -- was migration 0074 applied?", missing)
    if permissions:
        user.user_permissions.add(*permissions)


def activate_new_signup(user, wants_collaborator_access=False):
    """Self-serve signup activates immediately as a Basic account -- no
    admin approval wait. is_staff is deliberately left untouched (never
    granted automatically by any of this): it only controls Django-admin
    login, and self-serve accounts have no business there unless the owner
    manually flips it in the admin.

    If wants_collaborator_access is set, the account is still fully usable
    right away -- only a heads-up email to the superusers changes, so they
    can manually elevate the role from /users. Called with a user that may
    not be persisted yet (adapters call this instead of allauth's own
    commit=True save), so this is the save that actually creates the row --
    plain save(), not update_fields, since update_fields is an UPDATE-only
    optimization and this instance may still have no pk."""
    user.is_active = True
    user.role = User.Role.BASIC
    user.wants_collaborator_access = wants_collaborator_access
    user.save()
    _grant_default_permissions(user)
    if wants_collaborator_access:
        transaction.on_commit(lambda: _notify_collaborator_access_requested(user))
    return user


def reactivate_user(user):
    """Restore a previously revoked account -- back to active with the
    baseline permission grant, role untouched (stays whatever it was before
    revocation). Idempotent -- a bulk admin action can hit a mix of
    inactive and already-active rows, and reactivating an already-active
    user shouldn't re-send the "restored" email."""
    already_active = user.is_active
    user.is_active = True
    user.save(update_fields=["is_active"])
    _grant_default_permissions(user)
    if not already_active:
        transaction.on_commit(lambda: _notify_access_restored(user))
    return user


def reject_signup(user):
    """Delete an inactive account outright -- distinct from revoke_access(),
    which deactivates an *already-active* user without deleting their
    history. Only ever applies to a currently-inactive (is_active=False)
    account; refuses to touch anyone active."""
    if user.is_active:
        return False
    user.delete()
    return True


def revoke_access(user):
    """Deactivate an active account -- back to inactive, and every
    individually-granted permission cleared (a later reactivation starts
    clean with just the baseline again, rather than silently keeping
    whatever extra permissions this user had before). Refuses to touch a
    superuser (there's no UI path to re-grant superuser, so this could
    otherwise lock the owner out with no way back in short of a direct DB
    fix)."""
    if user.is_superuser:
        return user
    user.is_active = False
    user.save(update_fields=["is_active"])
    user.user_permissions.clear()
    return user


def _notify_collaborator_access_requested(user):
    recipients = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return
    display_name = user.name or user.get_username()
    try:
        send_mail(
            subject=f"Target Pathogen: {display_name} requested collaborator access",
            message=(
                f"{display_name} ({user.email}) signed up and is already using the site "
                'as a Basic account. They checked "Solicitar acceso de colaborador" -- '
                "review and assign a role from the Manage users screen if appropriate."
            ),
            html_message=render_to_string(
                "email/collaborator_access_requested_email.html",
                {"display_name": display_name, "user_email": user.email},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            "Failed to send collaborator-access-requested notification for user %s", user.pk
        )


def _notify_access_restored(user):
    if not user.email:
        return
    display_name = user.name or user.get_username()
    # Blank unless DJANGO_SITE_URL is set (see settings.py) -- there's no
    # reliable way to derive the site's real public URL from ALLOWED_HOSTS
    # or django.contrib.sites here, so a missing setting just means no link
    # instead of a guessed-wrong one.
    login_url = f"{settings.SITE_URL}{reverse('account_login')}" if settings.SITE_URL else ""
    try:
        send_mail(
            subject="Target Pathogen: your account access has been restored",
            message=(
                f"Hi {display_name}, your Target Pathogen account access "
                "has been restored. You can now sign in."
                + (f"\n\n{login_url}" if login_url else "")
            ),
            html_message=render_to_string(
                "email/user_approved_email.html",
                {"display_name": display_name, "login_url": login_url},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send access-restored notification for user %s", user.pk)

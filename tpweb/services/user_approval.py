"""New-account approval workflow: self-signups land inactive until the owner
approves them (see tpweb/adapters/AccountAdapters.py for where signups are
routed through mark_pending_approval, tpweb/admin/UserAdmin.py and
tpweb/views/UserManagementView.py for the two places approve_user() is
called from).
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

User = get_user_model()

# Every approved user gets this one automatically -- it's the baseline
# capability the whole approval flow exists for. The other named
# permissions (view Activity, curated import, BLAST, formulas, custom
# params, agent chat -- see TPUser.Meta.permissions) are NOT granted by
# default; the owner adds them per user from the Django admin's "user
# permissions" widget on that user's change form.
DEFAULT_APPROVED_PERMISSION_CODENAME = "can_upload_genome"


def _grant_default_permission(user):
    try:
        permission = Permission.objects.get(
            content_type__app_label="tpweb", codename=DEFAULT_APPROVED_PERMISSION_CODENAME
        )
    except Permission.DoesNotExist:
        # Migration 0074 hasn't run yet on this database -- shouldn't
        # happen in normal operation, but don't let a missing permission
        # row block approval itself.
        logger.warning(
            "Permission tpweb.%s not found -- was migration 0074 applied?",
            DEFAULT_APPROVED_PERMISSION_CODENAME,
        )
        return
    user.user_permissions.add(permission)


def mark_pending_approval(user):
    """Force a freshly-created account inactive until the owner approves it,
    then notify the owner(s) there's someone to review. Called with a user
    that may not be persisted yet (adapters call this instead of allauth's
    own commit=True save), so this is the save that actually creates the
    row -- plain save(), not update_fields, since update_fields is an
    UPDATE-only optimization and this instance may still have no pk."""
    user.is_active = False
    user.save()
    transaction.on_commit(lambda: _notify_new_signup(user))
    return user


def approve_user(user):
    """Grant an approved collaborator staff-level access. Idempotent -- a
    bulk admin action can hit a mix of pending and already-approved rows,
    and re-approving shouldn't re-send the "you're approved" email."""
    already_approved = user.is_active and user.is_staff
    user.is_active = True
    user.is_staff = True
    user.save(update_fields=["is_active", "is_staff"])
    _grant_default_permission(user)
    if not already_approved:
        transaction.on_commit(lambda: _notify_user_approved(user))
    return user


def reject_signup(user):
    """Delete a pending signup outright -- distinct from revoke_access(),
    which deactivates an *already-approved* user without deleting their
    history. Only ever applies to a still-pending (is_active=False)
    account; refuses to touch anyone already approved."""
    if user.is_active:
        return False
    user.delete()
    return True


def revoke_access(user):
    """Undo a prior approval -- back to inactive, no staff access, and
    every individually-granted permission cleared (a later re-approval
    starts clean with just the baseline again, rather than silently
    keeping whatever extra permissions this user had before). Refuses to
    touch a superuser (there's no UI path to re-grant superuser, so this
    could otherwise lock the owner out with no way back in short of a
    direct DB fix)."""
    if user.is_superuser:
        return user
    user.is_active = False
    user.is_staff = False
    user.save(update_fields=["is_active", "is_staff"])
    user.user_permissions.clear()
    return user


def _notify_new_signup(user):
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
            subject="Target Pathogen: new account pending approval",
            message=(
                f"{display_name} ({user.email}) just signed up "
                "and is waiting for approval. Review pending accounts in the admin "
                "panel or the Manage users screen."
            ),
            html_message=render_to_string(
                "email/new_signup_email.html",
                {"display_name": display_name, "user_email": user.email},
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send new-signup notification for user %s", user.pk)


def _notify_user_approved(user):
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
            subject="Target Pathogen: your account has been approved",
            message=(
                f"Hi {display_name}, your Target Pathogen account "
                "has been approved. You can now sign in."
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
        logger.exception("Failed to send approval notification for user %s", user.pk)

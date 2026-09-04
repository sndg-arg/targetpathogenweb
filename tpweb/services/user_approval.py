"""New-account approval workflow: self-signups land inactive until the owner
approves them (see tpweb/adapters/AccountAdapters.py for where signups are
routed through mark_pending_approval, tpweb/admin/UserAdmin.py and
tpweb/views/UserManagementView.py for the two places approve_user() is
called from).
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)

User = get_user_model()


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
    """Undo a prior approval -- back to inactive, no staff access. Refuses
    to touch a superuser (there's no UI path to re-grant superuser, so
    this could otherwise lock the owner out with no way back in short of
    a direct DB fix)."""
    if user.is_superuser:
        return user
    user.is_active = False
    user.is_staff = False
    user.save(update_fields=["is_active", "is_staff"])
    return user


def _notify_new_signup(user):
    recipients = list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return
    try:
        send_mail(
            subject="Target Pathogen: new account pending approval",
            message=(
                f"{user.get_username()} ({user.email}) just signed up and is "
                "waiting for approval. Review pending accounts in the admin "
                "panel or the Manage users screen."
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
    try:
        send_mail(
            subject="Target Pathogen: your account has been approved",
            message=(
                f"Hi {user.get_username()}, your Target Pathogen account has been "
                "approved. You can now sign in."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send approval notification for user %s", user.pk)

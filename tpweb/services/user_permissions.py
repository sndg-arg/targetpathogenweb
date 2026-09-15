"""Toggleable per-user permissions shown on the /users management screen's
edit-permissions modal -- lets the owner grant/revoke a collaborator's
individual permissions in-app, instead of sending them to Django admin's
own user_permissions widget (see tpweb/models/__init__.py's TPUser.Meta for
where these permissions are declared, and tpweb/services/user_approval.py
for can_upload_genome's automatic baseline grant on approval).
"""

from django.contrib.auth.models import Permission

PERMISSION_ORDER = [
    "can_upload_genome",
    "can_view_activity",
    "can_curated_import",
    "can_manage_formulas",
    "can_run_blast",
    "can_manage_custom_params",
    "can_use_agent_chat",
]


def _ordered_permissions():
    by_codename = {
        p.codename: p
        for p in Permission.objects.filter(
            content_type__app_label="tpweb", codename__in=PERMISSION_ORDER
        )
    }
    return [by_codename[codename] for codename in PERMISSION_ORDER if codename in by_codename]


def permission_choices():
    """[(codename, label), ...] in a stable display order -- the same list
    for every user regardless of what they're currently granted, used to
    render the modal's checkboxes once rather than per row."""
    return [(p.codename, p.name) for p in _ordered_permissions()]


def granted_codenames(user):
    """Which of the toggleable permissions this user currently holds."""
    return set(
        user.user_permissions.filter(
            content_type__app_label="tpweb", codename__in=PERMISSION_ORDER
        ).values_list("codename", flat=True)
    )


def set_user_permissions(user, codenames):
    """Replace user's toggleable tpweb permissions with exactly `codenames`
    (an iterable of codename strings) -- anything in PERMISSION_ORDER not in
    that set is revoked, anything in it is granted."""
    codenames = set(codenames)
    perms = _ordered_permissions()
    to_grant = [p for p in perms if p.codename in codenames]
    to_revoke = [p for p in perms if p.codename not in codenames]
    if to_grant:
        user.user_permissions.add(*to_grant)
    if to_revoke:
        user.user_permissions.remove(*to_revoke)

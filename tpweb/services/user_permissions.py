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
    "can_view_restricted_genomes",
    "can_view_human_targets",
]

# The single source of truth for what each named role grants -- keys match
# TPUser.Role 1:1 (minus "custom", which has no preset by definition: it's
# whatever's actually checked). Picking a role in the /users edit-permissions
# modal applies its exact codenames AND disables the checkboxes (the role
# IS the permission set, not a suggestion) -- see UserManagementView.post's
# update_permissions branch, which re-derives the codenames server-side from
# the submitted role rather than trusting whatever the client posted for
# "permissions", so a tampered request can't desync a named role from its
# real set. Superusers ("Admin: puedo hacer todo") aren't a preset here
# since they bypass every has_perm() check already and never see this modal
# (see manage.html: no Edit button on a superuser row).
PROFILE_PRESETS = [
    {
        # Self-serve signup baseline (tpweb.services.user_approval.
        # DEFAULT_APPROVED_PERMISSION_CODENAMES derives from this entry) --
        # deliberately excludes anything that exposes gated content or
        # queues real pipeline work, since Basic accounts activate with
        # zero human review.
        "key": "basic",
        "label": "Basic",
        "codenames": [
            "can_manage_formulas",
            "can_run_blast",
            "can_manage_custom_params",
            "can_use_agent_chat",
        ],
    },
    {
        # Bio-side collaborators on the Gates-Targets work itself (About us
        # page) -- everything except curated import (writes raw files into
        # a shared server directory, kept deliberately rare/manual).
        "key": "gates_collaborator",
        "label": "Gates collaborator",
        "codenames": [
            "can_upload_genome",
            "can_view_activity",
            "can_manage_formulas",
            "can_run_blast",
            "can_manage_custom_params",
            "can_use_agent_chat",
            "can_view_restricted_genomes",
            "can_view_human_targets",
        ],
    },
    {
        # Gates-side people who only consume the site (read genomes/targets,
        # run their own BLAST/formula work) -- no upload, no admin-ish
        # capabilities, no Human Targets (that's this app's own pilot
        # feature, not Gates-Targets output).
        "key": "gates_consumer",
        "label": "Gates consumer",
        "codenames": [
            "can_manage_formulas",
            "can_run_blast",
            "can_manage_custom_params",
            "can_use_agent_chat",
        ],
    },
    {
        # A shared classroom account for a TP: no upload (avoids every
        # student colliding in the same workspace) and no formulas/custom
        # params (one student editing a shared formula would silently
        # break the assignment for the whole class).
        "key": "student",
        "label": "Alumnos / testers",
        "codenames": [
            "can_run_blast",
            "can_use_agent_chat",
        ],
    },
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


def profile_presets():
    """[{key, label, codenames}, ...] for the modal's profile dropdown --
    filters each preset's codenames against PERMISSION_ORDER so a future
    permission rename/removal can't leave a stale codename checked."""
    valid_codenames = set(PERMISSION_ORDER)
    return [
        {
            "key": preset["key"],
            "label": preset["label"],
            "codenames": [c for c in preset["codenames"] if c in valid_codenames],
        }
        for preset in PROFILE_PRESETS
    ]


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

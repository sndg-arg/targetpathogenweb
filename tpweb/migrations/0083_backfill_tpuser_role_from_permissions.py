from django.db import migrations

# Frozen snapshot of tpweb.services.user_permissions.PROFILE_PRESETS as of this
# migration -- deliberately not imported live, since a migration's behavior
# must stay fixed even if the presets are edited later. Only used here to
# guess an existing user's role from their already-granted permissions; the
# live presets module is what the /users UI actually uses going forward.
PRESET_CODENAMES_BY_ROLE = {
    "gates_collaborator": frozenset(
        {
            "can_upload_genome",
            "can_view_activity",
            "can_manage_formulas",
            "can_run_blast",
            "can_manage_custom_params",
            "can_use_agent_chat",
            "can_view_restricted_genomes",
            "can_view_human_targets",
        }
    ),
    "gates_consumer": frozenset(
        {
            "can_manage_formulas",
            "can_run_blast",
            "can_manage_custom_params",
            "can_use_agent_chat",
        }
    ),
    "student": frozenset({"can_run_blast", "can_use_agent_chat"}),
}


def backfill_role(apps, schema_editor):
    """Best-effort only: if an existing active, non-superuser account's
    granted tpweb permissions exactly match one of today's PROFILE_PRESETS
    bundles, tag it with that role so it shows up correctly on /users
    without the owner having to reassign it by hand. Any user whose
    permissions don't exactly match a preset (hand-tweaked, or simply
    never matched one) is left at the "basic" default -- the owner should
    spot-check roles on /users after this migration runs rather than treat
    this as authoritative."""
    TPUser = apps.get_model("tpweb", "TPUser")

    for user in TPUser.objects.filter(is_active=True, is_superuser=False).exclude(
        username="public"
    ):
        granted = frozenset(
            user.user_permissions.filter(content_type__app_label="tpweb").values_list(
                "codename", flat=True
            )
        )
        for role, codenames in PRESET_CODENAMES_BY_ROLE.items():
            if granted == codenames:
                user.role = role
                user.save(update_fields=["role"])
                break


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0082_tpuser_role_and_collaborator_request"),
    ]

    operations = [
        migrations.RunPython(backfill_role, noop_reverse),
    ]

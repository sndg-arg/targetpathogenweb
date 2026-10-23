from django.contrib.auth.management import create_permissions
from django.db import migrations


def grant_to_already_approved_users(apps, schema_editor):
    """Same rationale as 0079_backfill_can_view_restricted_genomes -- a
    newly gated feature must not silently disappear for users who could
    already see it, so back-fill can_view_human_targets onto every account
    approved before this permission existed. The admin can then revoke it
    individually (from the /users "Edit" modal) for tester/student
    accounts."""
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Permission = apps.get_model("auth", "Permission")
    TPUser = apps.get_model("tpweb", "TPUser")
    try:
        permission = Permission.objects.get(
            content_type__app_label="tpweb", codename="can_view_human_targets"
        )
    except Permission.DoesNotExist:
        return
    for user in TPUser.objects.filter(is_active=True):
        user.user_permissions.add(permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0080_tpuser_can_view_human_targets"),
    ]

    operations = [
        migrations.RunPython(grant_to_already_approved_users, noop_reverse),
    ]

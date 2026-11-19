from django.contrib.auth.management import create_permissions
from django.db import migrations


def grant_to_already_approved_users(apps, schema_editor):
    """New restricted-genome checks must not silently hide genomes that
    already-approved users could already see -- so back-fill the same
    permission DEFAULT_APPROVED_PERMISSION_CODENAMES now grants to every
    freshly approved account (tpweb/services/user_approval.py) onto every
    account that was approved before this permission existed. The admin can
    then individually revoke it (from the /users "Edit" modal) for
    tester/student accounts that shouldn't see restricted genomes."""
    # Permission rows for a Meta.permissions change only get created by the
    # post_migrate signal after the whole `migrate` run finishes, so the one
    # added by migration 0078 doesn't exist yet at this point in the same
    # run -- create it now against the historical app registry.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Permission = apps.get_model("auth", "Permission")
    TPUser = apps.get_model("tpweb", "TPUser")
    try:
        permission = Permission.objects.get(
            content_type__app_label="tpweb", codename="can_view_restricted_genomes"
        )
    except Permission.DoesNotExist:
        return
    for user in TPUser.objects.filter(is_active=True):
        user.user_permissions.add(permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0078_tpuser_can_view_restricted_genomes"),
    ]

    operations = [
        migrations.RunPython(grant_to_already_approved_users, noop_reverse),
    ]

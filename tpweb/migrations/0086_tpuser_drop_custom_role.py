from django.db import migrations, models


def backfill_custom_role_to_basic(apps, schema_editor):
    # "Custom" (hand-picked permission checkboxes) is being retired -- /users
    # now only ever assigns a named role. Any row that landed on "custom"
    # keeps whatever individual permissions it already has (this migration
    # never touches user_permissions), it just needs a valid role label.
    TPUser = apps.get_model("tpweb", "TPUser")
    TPUser.objects.filter(role="custom").update(role="basic")


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0085_tpuser_role_custom_choice"),
    ]

    operations = [
        migrations.RunPython(backfill_custom_role_to_basic, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tpuser",
            name="role",
            field=models.CharField(
                choices=[
                    ("basic", "Basic"),
                    ("gates_collaborator", "Gates collaborator"),
                    ("gates_consumer", "Gates consumer"),
                    ("student", "Alumnos / testers"),
                ],
                default="basic",
                max_length=32,
                verbose_name="Role",
            ),
        ),
    ]

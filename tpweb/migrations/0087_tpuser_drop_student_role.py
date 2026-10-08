from django.db import migrations, models


def backfill_student_role_to_basic(apps, schema_editor):
    # "Alumnos / testers" is retired as a role -- the ladder is now
    # Visitor / Basic / Gates consumer / Gates collaborator / Admin. Any row
    # that landed on "student" keeps whatever individual permissions it
    # already has (this migration never touches user_permissions), it just
    # needs a valid role label.
    TPUser = apps.get_model("tpweb", "TPUser")
    TPUser.objects.filter(role="student").update(role="basic")


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0086_tpuser_drop_custom_role"),
    ]

    operations = [
        migrations.RunPython(backfill_student_role_to_basic, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tpuser",
            name="role",
            field=models.CharField(
                choices=[
                    ("basic", "Basic"),
                    ("gates_collaborator", "Gates collaborator"),
                    ("gates_consumer", "Gates consumer"),
                ],
                default="basic",
                max_length=32,
                verbose_name="Role",
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0081_backfill_can_view_human_targets"),
    ]

    operations = [
        migrations.AddField(
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
        migrations.AddField(
            model_name="tpuser",
            name="wants_collaborator_access",
            field=models.BooleanField(default=False, verbose_name="Requested collaborator access"),
        ),
    ]

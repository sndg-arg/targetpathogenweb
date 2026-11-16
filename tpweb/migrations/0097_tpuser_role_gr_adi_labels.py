from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0096_tpuser_collaborator_institution"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tpuser",
            name="role",
            field=models.CharField(
                choices=[
                    ("basic", "Basic"),
                    ("gates_collaborator", "Gr-ADI collaborator"),
                    ("gates_consumer", "Gr-ADI consumer"),
                ],
                default="basic",
                max_length=32,
                verbose_name="Role",
            ),
        ),
    ]

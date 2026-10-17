from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0084_agentchatmessagelog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tpuser",
            name="role",
            field=models.CharField(
                choices=[
                    ("basic", "Basic"),
                    ("gates_collaborator", "Gates collaborator"),
                    ("gates_consumer", "Gates consumer"),
                    ("student", "Alumnos / testers"),
                    ("custom", "Custom"),
                ],
                default="basic",
                max_length=32,
                verbose_name="Role",
            ),
        ),
    ]

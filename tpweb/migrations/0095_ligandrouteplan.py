from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0094_ligandreaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="LigandRoutePlan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("smiles_key", models.CharField(max_length=64, unique=True)),
                ("solved", models.BooleanField(default=False)),
                ("depth", models.PositiveSmallIntegerField(default=0)),
                ("steps", models.PositiveSmallIntegerField(default=0)),
                ("leaves", models.PositiveSmallIntegerField(default=0)),
                ("available_leaves", models.PositiveSmallIntegerField(default=0)),
                ("tree", models.JSONField()),
            ],
            options={"ordering": ["-solved", "steps", "id"]},
        ),
    ]

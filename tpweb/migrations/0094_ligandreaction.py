from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tpweb", "0093_sync_index_names_and_id_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="LigandReaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("smiles_key", models.CharField(db_index=True, max_length=64)),
                (
                    "db",
                    models.CharField(
                        choices=[("us50k", "USPTO-50K"), ("par2", "PaRoutes")], max_length=8
                    ),
                ),
                ("is_exact", models.BooleanField(default=True)),
                ("similarity", models.FloatField(blank=True, null=True)),
                ("reaction_id", models.CharField(max_length=64)),
                ("reaction_class", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("reaction_name", models.CharField(blank=True, default="", max_length=255)),
                ("reactants", models.TextField()),
                ("reagents", models.TextField(blank=True, default="")),
                ("product", models.TextField()),
            ],
            options={
                "ordering": ["-is_exact", "-similarity", "db", "id"],
            },
        ),
    ]

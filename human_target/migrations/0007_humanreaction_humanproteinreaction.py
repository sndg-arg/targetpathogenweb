import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0006_humancomplex_humanproteincomplex"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanReaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("bigg_id", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(blank=True, default="", max_length=512)),
                ("equation", models.TextField(blank=True, default="")),
                ("subsystem", models.CharField(blank=True, default="", max_length=255)),
                ("compartments", models.CharField(blank=True, default="", max_length=255)),
                ("reversible", models.BooleanField(default=False)),
                ("gene_rule", models.TextField(blank=True, default="")),
            ],
            options={"ordering": ["subsystem", "bigg_id"]},
        ),
        migrations.CreateModel(
            name="HumanProteinReaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "human_protein",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reaction_links",
                        to="human_target.humanprotein",
                    ),
                ),
                (
                    "reaction",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="protein_links",
                        to="human_target.humanreaction",
                    ),
                ),
            ],
            options={"unique_together": {("human_protein", "reaction")}},
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0005_humanprotein_summary_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanComplex",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("corum_id", models.PositiveIntegerField(unique=True)),
                ("name", models.CharField(max_length=512)),
                ("synonyms", models.TextField(blank=True, default="")),
                ("cell_line", models.TextField(blank=True, default="")),
                ("pmid", models.CharField(blank=True, default="", max_length=32)),
                ("comment", models.TextField(blank=True, default="")),
                ("disease_comment", models.TextField(blank=True, default="")),
                ("purification_methods", models.JSONField(blank=True, default=list)),
                ("go_terms", models.JSONField(blank=True, default=list)),
                ("subunits", models.JSONField(blank=True, default=list)),
            ],
            options={
                "verbose_name_plural": "human complexes",
                "ordering": ["name", "corum_id"],
            },
        ),
        migrations.CreateModel(
            name="HumanProteinComplex",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "complex",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="protein_links",
                        to="human_target.humancomplex",
                    ),
                ),
                (
                    "human_protein",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="complex_links",
                        to="human_target.humanprotein",
                    ),
                ),
            ],
            options={
                "ordering": ["complex__name", "complex__corum_id"],
                "unique_together": {("human_protein", "complex")},
            },
        ),
    ]

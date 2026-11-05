from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("human_target", "0002_humanprotein_expression_json"),
    ]

    operations = [
        migrations.CreateModel(
            name="HumanPathway",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("kegg_id", models.CharField(max_length=32, unique=True)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("entry_count", models.PositiveIntegerField(default=0)),
                ("relation_count", models.PositiveIntegerField(default=0)),
                ("graph_json", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "ordering": ["title", "kegg_id"],
                "verbose_name_plural": "human pathways",
            },
        ),
        migrations.CreateModel(
            name="HumanProteinPathway",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("highlighted_node_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "human_protein",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pathway_links",
                        to="human_target.humanprotein",
                    ),
                ),
                (
                    "pathway",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="protein_links",
                        to="human_target.humanpathway",
                    ),
                ),
            ],
            options={
                "ordering": ["pathway__title", "pathway__kegg_id"],
            },
        ),
        migrations.AlterUniqueTogether(
            name="humanproteinpathway",
            unique_together={("human_protein", "pathway")},
        ),
    ]

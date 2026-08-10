from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tpweb", "0060_curatedimportjob"),
    ]

    operations = [
        migrations.CreateModel(
            name="FilterPreset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("genome_name", models.CharField(max_length=255)),
                ("selected_parameters", models.JSONField(blank=True, default=list)),
                ("structure_source", models.CharField(blank=True, default="", max_length=64)),
                ("annotation_kind", models.CharField(blank=True, default="", max_length=32)),
                ("annotation_value", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="filter_presets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name", "id"],
                "indexes": [models.Index(fields=["owner", "genome_name", "name"], name="tpweb_filte_owner_i_71a1f3_idx")],
                "unique_together": {("owner", "genome_name", "name")},
            },
        ),
    ]

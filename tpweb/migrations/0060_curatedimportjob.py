from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0059_describe_offtarget_filter_cutoffs"),
    ]

    operations = [
        migrations.CreateModel(
            name="CuratedImportJob",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("genome_name", models.CharField(max_length=255)),
                ("results_tsv", models.CharField(max_length=1024)),
                ("structures_dir", models.CharField(blank=True, max_length=1024)),
                ("archive", models.CharField(blank=True, max_length=1024)),
                ("archive_root", models.CharField(blank=True, max_length=255)),
                ("ligq_output_dir", models.CharField(blank=True, max_length=1024)),
                (
                    "datadir",
                    models.CharField(
                        default="/app/targetpathogenweb/data",
                        max_length=1024,
                    ),
                ),
                ("overwrite_scores", models.BooleanField(default=True)),
                ("load_ligq_output", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("validated", "Validated"),
                            ("running", "Running"),
                            ("finished", "Finished"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="validated",
                        max_length=20,
                    ),
                ),
                ("phase", models.CharField(default="validated", max_length=64)),
                ("command", models.TextField(blank=True)),
                ("summary_json", models.JSONField(blank=True, default=dict)),
                ("stdout", models.TextField(blank=True)),
                ("stderr", models.TextField(blank=True)),
                ("report_path", models.CharField(blank=True, max_length=1024)),
                ("report_text", models.TextField(blank=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="curated_import_jobs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["owner", "status", "-created_at"],
                        name="tpweb_curat_owner_i_0c3c3a_idx",
                    ),
                    models.Index(
                        fields=["genome_name", "-created_at"],
                        name="tpweb_curat_genome__25026d_idx",
                    ),
                ],
            },
        ),
    ]

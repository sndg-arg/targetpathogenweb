from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0048_genomeupload"),
    ]

    operations = [
        migrations.CreateModel(
            name="PipelineRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("internal_accession", models.CharField(db_index=True, max_length=255)),
                ("source_accession", models.CharField(blank=True, default="", max_length=255)),
                ("gram", models.CharField(blank=True, default="", max_length=1)),
                ("custom_input", models.CharField(blank=True, default="", max_length=512)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("submitted", "Submitted"),
                            ("running", "Running"),
                            ("finished", "Finished"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="submitted",
                        max_length=24,
                    ),
                ),
                ("current_stage", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("current_stage_label", models.CharField(blank=True, default="", max_length=255)),
                ("current_app", models.CharField(blank=True, default="", max_length=128)),
                ("current_task_id", models.IntegerField(blank=True, null=True)),
                ("launch_pid", models.IntegerField(blank=True, null=True)),
                ("remote_job_id", models.CharField(blank=True, default="", max_length=64)),
                ("remote_job_dir", models.CharField(blank=True, default="", max_length=512)),
                ("run_log_path", models.CharField(blank=True, default="", max_length=512)),
                ("error_message", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "genome_upload",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="pipeline_runs",
                        to="tpweb.genomeupload",
                    ),
                ),
            ],
            options={"ordering": ("-started_at", "-id")},
        ),
        migrations.CreateModel(
            name="PipelineStageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stage_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("stage_label", models.CharField(blank=True, default="", max_length=255)),
                ("app_name", models.CharField(blank=True, default="", max_length=128)),
                ("task_id", models.IntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("submitted", "Submitted"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("info", "Info"),
                        ],
                        default="info",
                        max_length=24,
                    ),
                ),
                ("message", models.TextField(blank=True, default="")),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "pipeline_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stage_events",
                        to="tpweb.pipelinerun",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
    ]

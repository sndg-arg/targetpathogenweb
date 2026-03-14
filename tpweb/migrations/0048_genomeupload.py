# Generated manually for UI-based genome uploads.

from django.conf import settings
from django.db import migrations, models

from tpweb.models.GenomeUpload import genome_upload_path


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0047_workspace_owned_custom_params"),
    ]

    operations = [
        migrations.CreateModel(
            name="GenomeUpload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_accession", models.CharField(max_length=128)),
                ("internal_accession", models.CharField(max_length=255)),
                ("gram", models.CharField(choices=(("p", "Gram-positive"), ("n", "Gram-negative")), max_length=1)),
                ("gbk_file", models.FileField(upload_to=genome_upload_path)),
                ("status", models.CharField(choices=(("submitted", "Submitted"), ("running", "Running"), ("finished", "Finished"), ("failed", "Failed")), default="submitted", max_length=24)),
                ("launch_pid", models.IntegerField(blank=True, null=True)),
                ("run_log_path", models.CharField(blank=True, default="", max_length=512)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("launched_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="genome_uploads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]

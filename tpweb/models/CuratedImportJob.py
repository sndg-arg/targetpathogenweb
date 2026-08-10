from django.conf import settings
from django.db import models


class CuratedImportJob(models.Model):
    STATUS_VALIDATED = "validated"
    STATUS_RUNNING = "running"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_VALIDATED, "Validated"),
        (STATUS_RUNNING, "Running"),
        (STATUS_FINISHED, "Finished"),
        (STATUS_FAILED, "Failed"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="curated_import_jobs",
        on_delete=models.CASCADE,
    )
    genome_name = models.CharField(max_length=255)
    results_tsv = models.CharField(max_length=1024)
    structures_dir = models.CharField(max_length=1024, blank=True)
    archive = models.CharField(max_length=1024, blank=True)
    archive_root = models.CharField(max_length=255, blank=True)
    ligq_output_dir = models.CharField(max_length=1024, blank=True)
    datadir = models.CharField(max_length=1024, default="/app/targetpathogenweb/data")
    overwrite_scores = models.BooleanField(default=True)
    load_ligq_output = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_VALIDATED,
        db_index=True,
    )
    phase = models.CharField(max_length=64, default="validated")
    command = models.TextField(blank=True)
    summary_json = models.JSONField(default=dict, blank=True)
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    report_path = models.CharField(max_length=1024, blank=True)
    report_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status", "-created_at"]),
            models.Index(fields=["genome_name", "-created_at"]),
        ]

    @property
    def can_retry(self):
        return self.status == self.STATUS_FAILED

    def __str__(self):
        return f"{self.genome_name} curated import #{self.pk}"

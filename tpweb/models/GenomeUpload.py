from django.conf import settings
from django.db import models
from django.utils.text import slugify


def genome_upload_path(instance, filename):
    owner = getattr(instance, "owner", None)
    username = getattr(owner, "username", "") or "public"
    workspace_segment = slugify(username) or "public"
    internal_accession = slugify(instance.internal_accession) or "genome"
    return f"genome_uploads/{workspace_segment}/{internal_accession}/{filename}"


class GenomeUpload(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_RUNNING = "running"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_FINISHED, "Finished"),
        (STATUS_FAILED, "Failed"),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="genome_uploads",
        on_delete=models.CASCADE,
    )
    display_accession = models.CharField(max_length=128)
    internal_accession = models.CharField(max_length=255)
    gram = models.CharField(max_length=1, choices=(("p", "Gram-positive"), ("n", "Gram-negative")))
    gbk_file = models.FileField(upload_to=genome_upload_path)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    launch_pid = models.IntegerField(null=True, blank=True)
    run_log_path = models.CharField(max_length=512, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    launched_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.display_accession} ({self.owner.username})"

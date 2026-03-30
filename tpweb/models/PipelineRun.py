from django.db import models


class PipelineRun(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_RUNNING = "running"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RUNNING, "Running"),
        (STATUS_FINISHED, "Finished"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    genome_upload = models.ForeignKey(
        "tpweb.GenomeUpload",
        related_name="pipeline_runs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    internal_accession = models.CharField(max_length=255, db_index=True)
    source_accession = models.CharField(max_length=255, blank=True, default="")
    gram = models.CharField(max_length=1, blank=True, default="")
    custom_input = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    current_stage = models.PositiveSmallIntegerField(null=True, blank=True)
    current_stage_label = models.CharField(max_length=255, blank=True, default="")
    current_app = models.CharField(max_length=128, blank=True, default="")
    current_task_id = models.IntegerField(null=True, blank=True)
    launch_pid = models.IntegerField(null=True, blank=True)
    remote_job_id = models.CharField(max_length=64, blank=True, default="")
    remote_job_dir = models.CharField(max_length=512, blank=True, default="")
    run_log_path = models.CharField(max_length=512, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at", "-id")

    def __str__(self):
        return f"{self.internal_accession} [{self.status}]"


class PipelineStageEvent(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_INFO = "info"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_INFO, "Info"),
    )

    pipeline_run = models.ForeignKey(
        PipelineRun,
        related_name="stage_events",
        on_delete=models.CASCADE,
    )
    stage_number = models.PositiveSmallIntegerField(null=True, blank=True)
    stage_label = models.CharField(max_length=255, blank=True, default="")
    app_name = models.CharField(max_length=128, blank=True, default="")
    task_id = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_INFO)
    message = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        stage_text = f"stage {self.stage_number}" if self.stage_number else "stage ?"
        return f"{self.pipeline_run_id} {stage_text} {self.status}"

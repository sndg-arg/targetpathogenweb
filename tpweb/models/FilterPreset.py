from django.conf import settings
from django.db import models


class FilterPreset(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="filter_presets",
        on_delete=models.CASCADE,
    )
    genome_name = models.CharField(max_length=255)
    selected_parameters = models.JSONField(default=list, blank=True)
    structure_source = models.CharField(max_length=64, blank=True, default="")
    annotation_kind = models.CharField(max_length=32, blank=True, default="")
    annotation_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("owner", "genome_name", "name")
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["owner", "genome_name", "name"]),
        ]

    def __str__(self):
        return f"FilterPreset({self.genome_name}: {self.name})"

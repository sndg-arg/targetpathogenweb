from django.db import models


class HumanReaction(models.Model):
    """A Recon3D metabolic reaction (BiGG id), shared by every protein whose
    gene appears in its gene-reaction rule (see `HumanProteinReaction`).
    `equation` is rendered once at load time from metabolite names."""

    bigg_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=512, blank=True, default="")
    equation = models.TextField(blank=True, default="")
    subsystem = models.CharField(max_length=255, blank=True, default="")
    compartments = models.CharField(max_length=255, blank=True, default="")
    reversible = models.BooleanField(default=False)
    gene_rule = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["subsystem", "bigg_id"]

    def __str__(self):
        return f"{self.bigg_id} ({self.name})"

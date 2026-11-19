from django.db import models


class HumanComplex(models.Model):
    """A CORUM protein complex: shared reference data, linked to each member
    protein through `HumanProteinComplex`. `subunits` keeps every member as
    CORUM lists it ({accession, gene, name}), including members that are not
    in the human proteome table, so the page can name them all."""

    corum_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=512)
    synonyms = models.TextField(blank=True, default="")
    cell_line = models.TextField(blank=True, default="")
    pmid = models.CharField(max_length=32, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    disease_comment = models.TextField(blank=True, default="")
    purification_methods = models.JSONField(default=list, blank=True)
    go_terms = models.JSONField(default=list, blank=True)
    subunits = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name_plural = "human complexes"
        ordering = ["name", "corum_id"]

    def __str__(self):
        return f"CORUM {self.corum_id} ({self.name})"

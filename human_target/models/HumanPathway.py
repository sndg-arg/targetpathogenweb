from django.db import models


class HumanPathway(models.Model):
    """A KEGG pathway, shared reference data across every curated human
    protein that appears in it -- not per-protein content (see
    `HumanProteinPathway` for the per-protein link). `graph_json` is the
    pruned gene/ortholog node-edge graph parsed once from the pathway's KGML
    at ingest time (see `import_human_curated_proteins._parse_kgml`), not
    re-parsed per request.
    """

    kegg_id = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255, blank=True, default="")
    entry_count = models.PositiveIntegerField(default=0)
    relation_count = models.PositiveIntegerField(default=0)
    graph_json = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "human pathways"
        ordering = ["title", "kegg_id"]

    def __str__(self):
        return f"{self.kegg_id} ({self.title})"

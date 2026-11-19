from django.db import models

from .HumanPathway import HumanPathway
from .HumanProtein import HumanProtein


class HumanProteinPathway(models.Model):
    """Links a curated human protein to a KEGG pathway it appears in.
    `highlighted_node_id` is the pathway graph's own node id (matched at
    ingest time against this protein's NCBI GeneID cross-reference) so the
    Pathways tab can highlight/center this protein's node without
    re-deriving the match at render time."""

    human_protein = models.ForeignKey(
        HumanProtein, on_delete=models.CASCADE, related_name="pathway_links"
    )
    pathway = models.ForeignKey(
        HumanPathway, on_delete=models.CASCADE, related_name="protein_links"
    )
    highlighted_node_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        unique_together = ("human_protein", "pathway")
        ordering = ["pathway__title", "pathway__kegg_id"]

    def __str__(self):
        return f"{self.human_protein.uniprot_accession} · {self.pathway.kegg_id}"

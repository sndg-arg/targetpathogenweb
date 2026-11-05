from django.db import models

from .HumanProtein import HumanProtein
from .HumanReaction import HumanReaction


class HumanProteinReaction(models.Model):
    """Links a human protein to a Recon3D reaction its gene takes part in."""

    human_protein = models.ForeignKey(
        HumanProtein, on_delete=models.CASCADE, related_name="reaction_links"
    )
    reaction = models.ForeignKey(
        HumanReaction, on_delete=models.CASCADE, related_name="protein_links"
    )

    class Meta:
        unique_together = ("human_protein", "reaction")

    def __str__(self):
        return f"{self.human_protein.uniprot_accession} · {self.reaction.bigg_id}"

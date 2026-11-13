from django.db import models

from .HumanComplex import HumanComplex
from .HumanProtein import HumanProtein


class HumanProteinComplex(models.Model):
    """Links a human protein to a CORUM complex it is a subunit of."""

    human_protein = models.ForeignKey(
        HumanProtein, on_delete=models.CASCADE, related_name="complex_links"
    )
    complex = models.ForeignKey(
        HumanComplex, on_delete=models.CASCADE, related_name="protein_links"
    )

    class Meta:
        unique_together = ("human_protein", "complex")
        ordering = ["complex__name", "complex__corum_id"]

    def __str__(self):
        return f"{self.human_protein.uniprot_accession} · CORUM {self.complex.corum_id}"

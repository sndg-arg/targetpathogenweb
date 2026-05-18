
from django.db import models

from bioseq.models.Bioentry import Bioentry
from .pdb import PDB
from django.db.models import SmallIntegerField, CharField

class BioentryStructure(models.Model):
    bioentry = models.ForeignKey(Bioentry, models.CASCADE, related_name="structures")
    pdb = models.ForeignKey(PDB, models.CASCADE, related_name="sequences")
    chain = models.CharField(max_length=64, blank=True, default="")
    uniprot_start = models.IntegerField(null=True, blank=True)
    uniprot_end = models.IntegerField(null=True, blank=True)
    resolution = models.FloatField(null=True, blank=True)


class ExperimentalStructureXref(models.Model):
    bioentry = models.ForeignKey(
        Bioentry,
        models.CASCADE,
        related_name="experimental_structure_xrefs",
    )
    pdb_id = models.CharField(max_length=16)
    method = models.CharField(max_length=100, blank=True, default="")
    resolution = models.FloatField(null=True, blank=True)
    chains = models.CharField(max_length=128, blank=True, default="")
    uniprot_start = models.IntegerField(null=True, blank=True)
    uniprot_end = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = (("bioentry", "pdb_id"),)
        indexes = [
            models.Index(fields=["bioentry", "resolution"]),
            models.Index(fields=["pdb_id"]),
        ]

    @property
    def coverage_span(self):
        if self.uniprot_start is None or self.uniprot_end is None:
            return 0
        return max(0, self.uniprot_end - self.uniprot_start + 1)

# -*- coding: utf-8 -*-
from django.db import models

from bioseq.models.Bioentry import Bioentry


class MetabolicPathway(models.Model):
    SOURCE_KEGG = "KEGG"
    SOURCE_BIOCYC = "BIOCYC"
    SOURCE_CHOICES = (
        (SOURCE_KEGG, "KEGG"),
        (SOURCE_BIOCYC, "BioCyc"),
    )

    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = ("source", "external_id")

    def __str__(self):
        return f"{self.name} ({self.source}:{self.external_id})"


class MetabolicReaction(models.Model):
    genome_accession = models.CharField(max_length=128, db_index=True)
    reaction_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True, default="")
    ec_numbers = models.CharField(max_length=255, blank=True, default="")
    kegg_reaction_id = models.CharField(max_length=32, blank=True, default="")
    reversible = models.BooleanField(default=False)
    gpr_expression = models.TextField(blank=True, default="")
    pathways = models.ManyToManyField(MetabolicPathway, blank=True, related_name="reactions")

    class Meta:
        unique_together = ("genome_accession", "reaction_id")

    def __str__(self):
        return f"{self.reaction_id} ({self.genome_accession})"


class GeneReactionLink(models.Model):
    CHOKEPOINT_NONE = "none"
    CHOKEPOINT_PRODUCING = "producing"
    CHOKEPOINT_CONSUMING = "consuming"
    CHOKEPOINT_BOTH = "both"
    CHOKEPOINT_CHOICES = (
        (CHOKEPOINT_NONE, "Not a chokepoint"),
        (CHOKEPOINT_PRODUCING, "Producing chokepoint"),
        (CHOKEPOINT_CONSUMING, "Consuming chokepoint"),
        (CHOKEPOINT_BOTH, "Both producing and consuming chokepoint"),
    )

    bioentry = models.ForeignKey(
        Bioentry, on_delete=models.CASCADE,
        related_name="metabolic_reactions",
    )
    reaction = models.ForeignKey(MetabolicReaction, on_delete=models.CASCADE, related_name="genes")
    chokepoint_role = models.CharField(
        max_length=16, choices=CHOKEPOINT_CHOICES, default=CHOKEPOINT_NONE,
    )

    class Meta:
        unique_together = ("bioentry", "reaction")

    def __str__(self):
        return f"{self.bioentry_id} -> {self.reaction.reaction_id} ({self.chokepoint_role})"


class MetabolicReactionEdge(models.Model):
    genome_accession = models.CharField(max_length=128, db_index=True)
    reaction_a = models.ForeignKey(MetabolicReaction, on_delete=models.CASCADE, related_name="edges_a")
    reaction_b = models.ForeignKey(MetabolicReaction, on_delete=models.CASCADE, related_name="edges_b")

    class Meta:
        unique_together = ("genome_accession", "reaction_a", "reaction_b")

    def __str__(self):
        return f"{self.reaction_a.reaction_id} -- {self.reaction_b.reaction_id}"

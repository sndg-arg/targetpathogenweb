from django.conf import settings
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
    isoenzyme_count = models.PositiveSmallIntegerField(default=0)
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


class MetabolicSpecies(models.Model):
    """A metabolite (SBML species). `species_id` is the raw SBML species id — it's what
    `ReactionParticipant`/the source SBML's `speciesReference@species` actually reference,
    so we key on it directly rather than re-deriving a "clean" BioCyc frame id."""
    genome_accession = models.CharField(max_length=128, db_index=True)
    species_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default="")
    compartment = models.CharField(max_length=32, blank=True, default="")
    is_currency = models.BooleanField(default=False)

    class Meta:
        unique_together = ("genome_accession", "species_id")
        verbose_name_plural = "metabolic species"

    def __str__(self):
        return self.display_name or self.species_id


class ReactionParticipant(models.Model):
    ROLE_REACTANT = "reactant"
    ROLE_PRODUCT = "product"
    ROLE_CHOICES = (
        (ROLE_REACTANT, "Reactant"),
        (ROLE_PRODUCT, "Product"),
    )

    reaction = models.ForeignKey(MetabolicReaction, on_delete=models.CASCADE, related_name="participants")
    species = models.ForeignKey(MetabolicSpecies, on_delete=models.CASCADE, related_name="reactions")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    stoichiometry = models.FloatField(default=1.0)

    class Meta:
        unique_together = ("reaction", "species", "role")

    def __str__(self):
        return f"{self.reaction.reaction_id} {self.role}: {self.species.display_name} x{self.stoichiometry}"


class MetabolicImportRun(models.Model):
    """One row per `load_metabolism` run for a genome (re-running replaces it) — provenance
    for the thesis write-up and for debugging stale/mismatched data."""
    genome_accession = models.CharField(max_length=128, unique=True, db_index=True)
    sbml_filename = models.CharField(max_length=255, blank=True, default="")
    results_filename = models.CharField(max_length=255, blank=True, default="")
    sif_filename = models.CharField(max_length=255, blank=True, default="")
    imported_at = models.DateTimeField(auto_now=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )

    def __str__(self):
        return f"{self.genome_accession} ({self.imported_at:%Y-%m-%d})"

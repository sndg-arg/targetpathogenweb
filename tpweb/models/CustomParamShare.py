from django.db import models

from tpweb.models.ScoreParam import ScoreParam


class CustomParamShare(models.Model):
    """Who else can see one uploaded ("Custom") column on one genome. No row
    means private to the owner. Deleting the column (or the owner) drops
    every share with it -- see tpweb.services.custom_param_sharing."""

    VISIBILITY_PROJECT = "project"
    VISIBILITY_PUBLIC = "public"
    VISIBILITY_CHOICES = (
        (VISIBILITY_PROJECT, "Project members"),
        (VISIBILITY_PUBLIC, "Everyone who can see this genome"),
    )

    score_param = models.ForeignKey(
        ScoreParam, related_name="genome_shares", on_delete=models.CASCADE
    )
    # Internal Biodatabase name, same key RestrictedGenome uses.
    genome_name = models.CharField(max_length=255)
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES)
    shared_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("score_param", "genome_name"),
                name="tpweb_customparamshare_param_genome_unique",
            ),
        ]

    def __str__(self):
        return f"{self.score_param.name} on {self.genome_name}: {self.visibility}"

from django.db import models


class LigandRoutePlan(models.Model):
    """A multi-step synthesis tree for a ligand, built by expand_ligand_routes
    on the cluster: the best depth-bounded plan found over USPTO-50K and
    PaRoutes. One plan per ligand; see tpweb/services/ligand_routes.py."""

    smiles_key = models.CharField(max_length=64, unique=True)
    solved = models.BooleanField(default=False)
    depth = models.PositiveSmallIntegerField(default=0)
    steps = models.PositiveSmallIntegerField(default=0)
    leaves = models.PositiveSmallIntegerField(default=0)
    available_leaves = models.PositiveSmallIntegerField(default=0)
    tree = models.JSONField()

    class Meta:
        ordering = ["-solved", "steps", "id"]

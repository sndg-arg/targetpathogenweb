import hashlib

from django.db import models


def ligand_smiles_key(smiles):
    """Lookup key for a ligand: its SMILES exactly as stored in Binders."""
    return hashlib.sha256((smiles or "").strip().encode("utf-8")).hexdigest()


class LigandReaction(models.Model):
    """A patent reaction whose product is a ligand (exact) or a close analog
    (similar), from USPTO-50K or PaRoutes; see predict_ligand_reactions."""

    DB_USPTO50K = "us50k"
    DB_PAROUTES = "par2"
    DB_CHOICES = ((DB_USPTO50K, "USPTO-50K"), (DB_PAROUTES, "PaRoutes"))

    smiles_key = models.CharField(max_length=64, db_index=True)
    db = models.CharField(max_length=8, choices=DB_CHOICES)
    is_exact = models.BooleanField(default=True)
    similarity = models.FloatField(null=True, blank=True)
    reaction_id = models.CharField(max_length=64)
    reaction_class = models.PositiveSmallIntegerField(null=True, blank=True)
    reaction_name = models.CharField(max_length=255, blank=True, default="")
    reactants = models.TextField()
    reagents = models.TextField(blank=True, default="")
    product = models.TextField()

    class Meta:
        ordering = ["-is_exact", "-similarity", "db", "id"]

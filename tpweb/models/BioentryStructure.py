
from django.db import models

from bioseq.models.Bioentry import Bioentry
from .pdb import PDB
from django.db.models import SmallIntegerField, CharField

class BioentryStructure(models.Model):
    bioentry = models.ForeignKey(Bioentry, models.CASCADE, related_name="structures")
    pdb = models.ForeignKey(PDB, models.CASCADE, related_name="sequences")

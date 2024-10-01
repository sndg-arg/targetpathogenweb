# -*- coding: utf-8 -*-
from django.db import models


class Binders(models.Model):

    id = models.AutoField(primary_key=True)
    ccd_id = models.CharField(max_length=255)
    pdb_id = models.CharField(max_length=255)
    uniprot = models.CharField(max_length=255)
    locustag = models.CharField(max_length=255)
    smiles = models.CharField(max_length=255)

    def __str__(self):
        return f"Ligand ID: {self.ccd_id}, PDB: {self.pdb_id}, UNIPROT: {self.uniprot}, Locustag: {self.locustag}, SMILES: {self.smiles}"

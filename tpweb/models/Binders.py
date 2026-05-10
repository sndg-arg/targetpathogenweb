# -*- coding: utf-8 -*-
from django.db import models
from bioseq.models.Bioentry import Bioentry


class Binders(models.Model):
    SOURCE_PDB = "pdb"
    SOURCE_PROPOSED = "proposed"
    SOURCE_CHOICES = (
        (SOURCE_PDB, "PDB"),
        (SOURCE_PROPOSED, "Proposed"),
    )

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    ccd_id = models.CharField(max_length=255)
    pdb_id = models.CharField(max_length=255, blank=True, default="")
    uniprot = models.CharField(max_length=255, blank=True, default="")
    locustag = models.ForeignKey(Bioentry, on_delete=models.CASCADE, to_field='accession')
    smiles = models.TextField()
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_PDB,
        db_index=True,
    )
    score = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Ligand ID: {self.ccd_id}, PDB: {self.pdb_id}, UNIPROT: {self.uniprot}, Locustag: {self.locustag}, SMILES: {self.smiles}"

# -*- coding: utf-8 -*-
from django.db import models
from bioseq.models.Bioentry import Bioentry


class Binders(models.Model):

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')
    ccd_id = models.CharField(max_length=255)
    pdb_id = models.CharField(max_length=255)
    uniprot = models.CharField(max_length=255)
    locustag = models.ForeignKey(Bioentry, on_delete=models.CASCADE, to_field='accession')
    smiles = models.CharField(max_length=255)

    def __str__(self):
        return f"Ligand ID: {self.ccd_id}, PDB: {self.pdb_id}, UNIPROT: {self.uniprot}, Locustag: {self.locustag}, SMILES: {self.smiles}"

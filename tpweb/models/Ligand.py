from django.db import models
from bioseq.models.Bioentry import Bioentry

class Ligand(models.Model):
    ligand_id = models.AutoField(primary_key=True)
    ligand_from_key = models.CharField(max_length=255, unique=True)
    ligand_smiles = models.CharField(max_length=10000)

    def __str__(self):
        return f"Ligand ID: {self.ligand_id},FROM: {self.ligand_from_key} ,SMILES: {self.ligand_smiles}"
    
class AccessionLigand(models.Model):
    relation_id = models.AutoField(primary_key=True)
    locus_tag = models.ForeignKey(Bioentry, on_delete=models.CASCADE, to_field='accession')
    ligand = models.ForeignKey(Ligand, on_delete=models.CASCADE, to_field='ligand_from_key')
    reference = models.CharField(max_length=255)
    reference_type = models.CharField(max_length=255)
    class Meta:
        unique_together = ('locus_tag', 'ligand', 'reference_type')
from django.db import models
from bioseq.models.Bioentry import Bioentry
    
class Pathway(models.Model):
    path_id = models.AutoField(primary_key=True)
    locus_tag = models.ForeignKey(Bioentry, on_delete=models.CASCADE, to_field='accession')
    pathway = models.CharField(max_length=255)
    class Meta:
        unique_together = ('locus_tag', 'pathway')


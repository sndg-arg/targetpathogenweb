from django.db import models
from bioseq.io.SeqStore import SeqStore



def save_location(instance, filename):
    # Assuming SeqStore().db_dir() returns a directory path based on the accession
    ss = SeqStore('./')
    # Use the accession value from the instance to determine the upload location
    return f'{ss.db_dir(instance.accession)}/{filename}'

class CustomParam(models.Model):
    accession = models.CharField(max_length=64)
    tsv = models.FileField(upload_to=save_location)

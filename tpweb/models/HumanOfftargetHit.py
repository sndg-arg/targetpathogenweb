from django.db import models

from bioseq.models.Bioentry import Bioentry


class HumanOfftargetHit(models.Model):
    """One human protein the pathogen protein hit in FastTarget's BLASTP
    screen (offtarget/human_offtarget_blast.tsv), best HSP per human protein.
    Loaded by fast_command / load_human_offtarget_hits; shown on the protein
    page via tpweb.services.human_offtarget_hits."""

    bioentry = models.ForeignKey(Bioentry, models.CASCADE, related_name="human_offtarget_hits")
    human_accession = models.CharField(max_length=32)
    human_entry_name = models.CharField(max_length=64, blank=True, default="")
    identity = models.FloatField()
    evalue = models.FloatField()
    bitscore = models.FloatField(null=True, blank=True)
    alignment_length = models.IntegerField(null=True, blank=True)
    query_start = models.IntegerField(null=True, blank=True)
    query_end = models.IntegerField(null=True, blank=True)
    subject_start = models.IntegerField(null=True, blank=True)
    subject_end = models.IntegerField(null=True, blank=True)
    query_coverage = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = (("bioentry", "human_accession"),)
        indexes = [models.Index(fields=["bioentry"], name="tpweb_humhit_bioentry_idx")]

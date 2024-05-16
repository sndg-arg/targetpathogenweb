# -*- coding: utf-8 -*-
from django.db import models
from bioseq.models.Bioentry import Bioentry


class CelularLocalization(models.Model):
    localization_id = models.AutoField(primary_key=True)
    locus_tag = models.ForeignKey(Bioentry, on_delete=models.CASCADE, to_field='accession')
    localization = models.CharField(max_length=255)
    class Meta:
        unique_together = ('locus_tag', 'localization')

    def __str__(self):
        return f"LocusTag: {self.locus_tag}, Localization: {self.localization}"
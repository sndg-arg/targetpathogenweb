from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.db.models import SmallIntegerField, CharField, FloatField

from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParam import ScoreParam


class ScoreParamValue(models.Model):
    score_param = models.ForeignKey(ScoreParam,
                                    on_delete=models.CASCADE)
    bioentry = models.ForeignKey(Bioentry, related_name='score_params',
                                 on_delete=models.CASCADE)

    value = CharField(blank=True, default="")
    numeric_value = FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('score_param', 'bioentry',)

    def __repr__(self):
        return f'ScoreParamValue({self.bioentry.accession} - {self.score_param.name}) = {self.value}'

    def __str__(self):
        return self.__repr__()

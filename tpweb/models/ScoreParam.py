from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.db.models import SmallIntegerField, CharField, TextField


class ScoreParam(models.Model):
    category = CharField(max_length=255)
    name = CharField(max_length=255, unique=True)
    type = CharField(max_length=255, choices=["CATEGORICAL", "NUMERIC"])
    default_operation = CharField(max_length=255)
    default_value = CharField(max_length=255)
    description = TextField(max_length=255)

    class Meta:
        unique_together = ('category', 'name',)

    @staticmethod
    def initialize():
        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="druggability", type="NUMERIC",
            default_operation=">",default_value="Y")[0]

        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="catalitic_site", type="CATEGORICAL",
            default_operation="=",default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="N")

        sp = ScoreParam.objects.get_or_create(
            category="Structure", name="ligand_aln", type="CATEGORICAL",
            default_operation="=",default_value="Y")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="N")

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_conserv", type="CATEGORICAL",
            decription="Pocket with sites of low conservation within the species",
            default_operation="=",default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")

        sp = ScoreParam.objects.get_or_create(
            category="Pocket", name="pocket_conserv_coli", type="CATEGORICAL",
            decription="Pocket with sites of low conservation against Ecoli.",
            default_operation="=",default_value="N")[0]
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")
        ScoreParamOptions.objects.get_or_create(score_param=sp,value="Y")


class ScoreParamOptions(models.Model):
    score_param = models.ForeignKey(ScoreParam, related_name='choices',
                                    on_delete=models.PROTECT)
    value = CharField(max_length=255)
    description = TextField(max_length=255)

    class Meta:
        unique_together = ('score_param', 'value',)

from ckeditor_uploader.fields import RichTextUploadingField
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import SmallIntegerField, CharField, FloatField

from bioseq.models.Bioentry import Bioentry
from tpweb.models.ScoreParam import ScoreParam
from tpweb.models.ScoreParamValue import ScoreParamValue

User = get_user_model()


class ScoreFormula(models.Model):
    name = CharField(max_length=255, blank=False)
    user = models.ForeignKey(User, related_name='formulas',
                             on_delete=models.CASCADE, null=True)
    default = models.BooleanField(default=False)
    public = models.BooleanField(default=False)


    class Meta:
        unique_together = ('name', 'user',)

    def __repr__(self):
        return f'ScoreFormula({self.name})'

    def __str__(self):
        return self.__repr__()

    def score(self, be: Bioentry):
        param_values = {spv.score_param.name: spv.value for spv in be.score_params.all()}
        return sum([term.score(param_values[term.score_param.name]) for term in self.terms.all()
                    if term.score_param.name in param_values])





class ScoreFormulaParam(models.Model):
    formula = models.ForeignKey(ScoreFormula, related_name='params',
                                on_delete=models.CASCADE)
    score_param = models.ForeignKey(ScoreParam, on_delete=models.PROTECT)

    value = CharField(blank=True, default="")

    operation = CharField(max_length=50, blank=False)
    coefficient = FloatField(null=False, blank=False)

    class Meta:
        unique_together = ('formula', 'score_param', "value")

    def __repr__(self):
        return f'ScoreFormulaParam({self.score_param.name} - {self.coefficient}) = {self.value}'

    def __str__(self):
        return self.__repr__()

    def score(self, value):
        if self.operation == "=":
            if self.value == value:
                return self.coefficient
        return 0

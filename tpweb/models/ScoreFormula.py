from ckeditor_uploader.fields import RichTextUploadingField
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import CharField, FloatField

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

    def get_current_formula(self):
        terms = {}
        for t in self.terms.all():
            if t.score_param.name in terms:
                terms[t.score_param.name].append(t)
            else:
                terms[t.score_param.name] = [t]
        terms2 = {}
        for param_name, ts in terms.items():
            for t in ts:
                terms2[t.value] = t.coefficient
        result = ""
        for i, (key, value) in enumerate(terms2.items()):
            if int(value) < 0:
                result += f"({value}) x {key}"
            else:
                result += f"{value} x {key}"
            if i < len(terms2) - 1:
                result += " + "
        formuladto = f"{self.name} = {result}"
        return formuladto
    def get_current_coefficients(self):
        terms = []
        for t in self.terms.all():
            t = {"param" : t.score_param.name, "option" : t.value, "coefficient" : t.coefficient}
            terms.append(t)
        return terms



class ScoreFormulaParam(models.Model):
    id = models.AutoField(primary_key=True)
    formula = models.ForeignKey(ScoreFormula, related_name='terms',
                                on_delete=models.CASCADE)
    score_param = models.ForeignKey(ScoreParam, on_delete=models.PROTECT)

    value = CharField(max_length=255, blank=True, default="")

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

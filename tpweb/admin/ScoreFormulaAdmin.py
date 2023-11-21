from tpweb.models.ScoreFormula import ScoreFormulaParam, ScoreFormula
from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB

from django.contrib import admin


class ScoreFormulaAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "terms_str"]
    search_fields = ["name", "user"]

    @admin.display(description="terms")
    def terms_str(self, obj):
        return " + ".join([str(x.coefficient) + " " + x.score_param.name
                           for x in obj.terms.all()])


admin.site.register(ScoreFormula, ScoreFormulaAdmin)

from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB

from django.contrib import admin


class ScoreFormulaParamAdmin(admin.ModelAdmin):
    list_display = ["formula_name", "operation", "coefficient", "param_name","value"]
    search_fields = ["params__score_param__name", "formula__name"]



    @admin.display(description="value")
    def formula_name(self, obj):
        return obj.formula.name
    @admin.display(description="param_name")
    def param_name(self, obj):
        return obj.score_param.name


admin.site.register(ScoreFormulaParam, ScoreFormulaParamAdmin)

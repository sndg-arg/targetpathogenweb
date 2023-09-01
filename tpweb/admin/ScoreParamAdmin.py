from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue
from tpweb.models.pdb import PDB

from django.contrib import admin




class ScoreParamAdmin(admin.ModelAdmin):

    list_display = ["name", "category", "type","default_operation","default_value","description","choices_names"]
    search_fields = ["name","category","description"]

    @admin.display(description="Choices")
    def choices_names(self, obj):
        return " ".join({x.name for x in obj.choices.all() })



admin.site.register(ScoreParam, ScoreParamAdmin)




class ScoreParamOptionsAdmin(admin.ModelAdmin):

    list_display = ["name", "description", "score_param_name"]
    search_fields = ["name","description","score_param__name"]
    raw_id_fields = (
        'score_param',
    )

    @admin.display(description="Score param")
    def score_param_name(self, obj):
        return obj.score_param.name

admin.site.register(ScoreParamOptions, ScoreParamOptionsAdmin)



class ScoreParamValueAdmin(admin.ModelAdmin):

    list_display = ["bioentry_accession", "score_param_name","value","numeric_value"]
    search_fields = ["bioentry__accession", "score_param__name"]
    raw_id_fields = (
        'bioentry','score_param',
    )

    @admin.display(description="Sequence")
    def bioentry_accession(self, obj):
        return obj.bioentry.accession
    @admin.display(description="Score param")
    def score_param_name(self, obj):
        return obj.score_param.name

admin.site.register(ScoreParamValue, ScoreParamValueAdmin)
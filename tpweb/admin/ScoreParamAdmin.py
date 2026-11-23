from tpweb.models.CustomParamShare import CustomParamShare
from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.models.ScoreParamValue import ScoreParamValue

from django.contrib import admin

from tpweb.admin.private_data import HideResearcherDataMixin


class ScoreParamAdmin(HideResearcherDataMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "category",
        "type",
        "default_operation",
        "default_value",
        "description",
        "choices_names",
    ]
    search_fields = ["name", "category", "description"]

    @admin.display(description="Choices")
    def choices_names(self, obj):
        return " ".join({x.name for x in obj.choices.all()})


admin.site.register(ScoreParam, ScoreParamAdmin)


class ScoreParamOptionsAdmin(HideResearcherDataMixin, admin.ModelAdmin):
    owner_path = "score_param__"
    list_display = ["name", "description", "score_param_name"]
    search_fields = ["name", "description", "score_param__name"]
    raw_id_fields = ("score_param",)

    @admin.display(description="Score param")
    def score_param_name(self, obj):
        return obj.score_param.name


admin.site.register(ScoreParamOptions, ScoreParamOptionsAdmin)


class ScoreParamValueAdmin(HideResearcherDataMixin, admin.ModelAdmin):
    owner_path = "score_param__"
    list_display = ["bioentry_accession", "score_param_name", "value", "numeric_value"]
    search_fields = ["bioentry__accession", "score_param__name"]
    raw_id_fields = (
        "bioentry",
        "score_param",
    )

    @admin.display(description="Sequence")
    def bioentry_accession(self, obj):
        return obj.bioentry.accession

    @admin.display(description="Score param")
    def score_param_name(self, obj):
        return obj.score_param.name


admin.site.register(ScoreParamValue, ScoreParamValueAdmin)


class CustomParamShareAdmin(HideResearcherDataMixin, admin.ModelAdmin):
    owner_path = "score_param__"
    list_display = ["score_param", "genome_name", "visibility", "shared_at"]
    list_filter = ["visibility"]
    search_fields = ["score_param__name", "genome_name"]
    raw_id_fields = ("score_param",)


admin.site.register(CustomParamShare, CustomParamShareAdmin)

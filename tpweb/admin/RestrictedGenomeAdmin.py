from django.contrib import admin

from tpweb.models.RestrictedGenome import RestrictedGenome


@admin.register(RestrictedGenome)
class RestrictedGenomeAdmin(admin.ModelAdmin):
    list_display = ["genome_name", "note", "restricted_by", "created_at"]
    search_fields = ["genome_name", "note"]
    list_select_related = ["restricted_by"]

    def save_model(self, request, obj, form, change):
        if not obj.restricted_by_id:
            obj.restricted_by = request.user
        super().save_model(request, obj, form, change)

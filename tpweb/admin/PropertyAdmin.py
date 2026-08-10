from django.contrib import admin


from tpweb.models.pdb import Property


class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name", "description"]


admin.site.register(Property, PropertyAdmin)

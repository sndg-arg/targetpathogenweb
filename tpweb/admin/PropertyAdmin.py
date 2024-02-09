from django.contrib import admin

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from tpweb.models.pdb import Property

from django.contrib import admin



class PropertyAdmin(admin.ModelAdmin):

    list_display = ["name", "description"]
    search_fields = ["name", "description"]

    

admin.site.register(Property, PropertyAdmin)

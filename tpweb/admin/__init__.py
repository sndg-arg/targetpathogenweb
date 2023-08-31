from tpweb.models.BioentryStructure import BioentryStructure
from django.contrib import admin
from tpweb.admin.UserAdmin import UserAdmin
str(UserAdmin)

class BioentryStructureAdmin(admin.ModelAdmin):
    pass


admin.site.register(BioentryStructure, BioentryStructureAdmin)

import tpweb.admin.PDBAdmin

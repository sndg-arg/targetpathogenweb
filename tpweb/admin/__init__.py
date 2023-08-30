from tpweb.models.BioentryStructure import BioentryStructure
from django.contrib import admin


class BioentryStructureAdmin(admin.ModelAdmin):
    pass


admin.site.register(BioentryStructure, BioentryStructureAdmin)

import tpweb.admin.PDBAdmin

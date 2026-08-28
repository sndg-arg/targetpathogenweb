from django.contrib import admin

import tpweb.admin.PDBAdmin as PDBAdmin
import tpweb.admin.PropertyAdmin as PropertyAdmin
import tpweb.admin.RequestLogAdmin as RequestLogAdmin
import tpweb.admin.ScoreFormulaAdmin as ScoreFormulaAdmin
import tpweb.admin.ScoreParamAdmin as ScoreParamAdmin
import tpweb.admin.TPPostAdmin as TPPostAdmin
import tpweb.admin.UserAdmin as UserAdmin
from tpweb.models.BioentryStructure import BioentryStructure

__all__ = [
    "PDBAdmin",
    "PropertyAdmin",
    "RequestLogAdmin",
    "ScoreFormulaAdmin",
    "ScoreParamAdmin",
    "TPPostAdmin",
    "UserAdmin",
]


class BioentryStructureAdmin(admin.ModelAdmin):
    pass


admin.site.register(BioentryStructure, BioentryStructureAdmin)

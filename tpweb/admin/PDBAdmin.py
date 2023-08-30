from django.contrib import admin

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from tpweb.models.pdb import PDB

from django.contrib import admin



class PDBAdmin(admin.ModelAdmin):

    list_display = ["code", "bioentry_name", "chains_list","residues_count"]
    search_fields = ["name"]

    @admin.display(description="Chains List")
    def chains_list(self, obj):
        return " ".join({x.chain for x in obj.residues.all() })

    @admin.display(description="Total Residues")
    def residues_count(self, obj):
        return obj.residues.count()

    @admin.display(description="Sequence")
    def bioentry_name(self, obj):
        return obj.sequences.all()[0].bioentry.name

admin.site.register(PDB, PDBAdmin)
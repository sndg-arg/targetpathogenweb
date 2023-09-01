from django.contrib import admin

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from tpweb.models.pdb import PDB, PDBResidueSet, ResidueSet

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
        seqs = obj.sequences.all()
        if seqs:
            return seqs[0].bioentry.accession
        else:
            return "-"

admin.site.register(PDB, PDBAdmin)

class PDBResidueSetAdmin(admin.ModelAdmin):

    list_display = ["name", "pdb_name", "residue_set_name"]
    search_fields = ["name","residue_set__name","pdb__code"]

    @admin.display(description="residues")
    def chains_list(self, obj):
        return " ".join({x.chain for x in obj.residues.all() })

    @admin.display(description="Total Residues")
    def residue_set_name(self, obj):
        return obj.residue_set.name

    @admin.display(description="Structure")
    def pdb_name(self, obj):
        return obj.pdb.code

admin.site.register(PDBResidueSet, PDBResidueSetAdmin)

class ResidueSetAdmin(admin.ModelAdmin):

    list_display = ["name", "description"]
    search_fields = ["name","description"]



admin.site.register(ResidueSet, ResidueSetAdmin)
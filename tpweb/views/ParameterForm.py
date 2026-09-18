"""Shared helpers for form widgets and label humanisation.

Originally housed the legacy ParameterForm used by the standalone advanced-filters
page. That page was folded into the protein list filters drawer; this module now
keeps only the bits other forms still depend on (FormulaForm uses
HumanizedModelChoiceField, several views call humanize_identifier).
"""

from django import forms

from tpweb.services.protein_list import humanize_identifier


class HumanizedModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        if hasattr(obj, "name"):
            return humanize_identifier(obj.name)
        return super().label_from_instance(obj)

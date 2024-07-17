from django import forms
from tpweb.models.CustomParamFile import CustomParam


class CustomParamForm(forms.ModelForm):
    class Meta:
        model = CustomParam
        fields = ('tsv',)

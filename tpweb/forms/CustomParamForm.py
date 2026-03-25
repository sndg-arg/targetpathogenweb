from django import forms
from tpweb.models.CustomParamFile import CustomParam


class CustomParamForm(forms.ModelForm):
    class Meta:
        model = CustomParam
        fields = ('tsv',)
        widgets = {
            'tsv': forms.ClearableFileInput(attrs={'class': 'tp-file-input'}),
        }

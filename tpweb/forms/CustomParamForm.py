import os

from django import forms

from tpweb.models.CustomParamFile import CustomParam


class CustomParamForm(forms.ModelForm):
    class Meta:
        model = CustomParam
        fields = ("tsv",)
        widgets = {
            "tsv": forms.ClearableFileInput(attrs={"class": "tp-file-input"}),
        }

    def clean_tsv(self):
        uploaded = self.cleaned_data.get("tsv")
        filename = str(getattr(uploaded, "name", "") or "").lower()
        if not filename.endswith((".tsv", ".csv")):
            raise forms.ValidationError("Upload a .tsv or .csv file.")
        max_size = int(os.environ.get("TPW_CUSTOM_PARAM_UPLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
        if getattr(uploaded, "size", 0) > max_size:
            raise forms.ValidationError(f"File too large. Limit: {max_size // (1024 * 1024)} MB.")
        return uploaded

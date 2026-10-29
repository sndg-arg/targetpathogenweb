import os

from django import forms

from tpweb.models.CustomParamFile import CustomParam
from tpweb.services.custom_param_sharing import VISIBILITY_LABELS, VISIBILITY_PRIVATE


class CustomParamForm(forms.ModelForm):
    # Who else sees the uploaded columns on this genome; choices depend on
    # whether the genome is restricted, see custom_param_sharing.
    visibility = forms.ChoiceField(
        choices=(),
        initial=VISIBILITY_PRIVATE,
        widget=forms.RadioSelect,
    )
    description = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control tp-ui-control", "rows": 3}),
    )

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

    def __init__(self, *args, visibility_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["visibility"].choices = visibility_choices or list(VISIBILITY_LABELS.items())

    def clean(self):
        cleaned = super().clean()
        visibility = cleaned.get("visibility")
        description = (cleaned.get("description") or "").strip()
        cleaned["description"] = description
        if visibility and visibility != VISIBILITY_PRIVATE and not description:
            self.add_error(
                "description",
                "Add a short description so others know what the values mean.",
            )
        return cleaned

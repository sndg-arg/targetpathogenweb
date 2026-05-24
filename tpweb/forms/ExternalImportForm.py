from django import forms
from django.utils.translation import gettext_lazy as _


class ExternalImportForm(forms.Form):
    genome_name = forms.CharField(
        label=_("TPW genome name"),
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control tp-ui-control",
                "placeholder": "public__KpATCC43816",
            }
        ),
    )
    results_tsv = forms.CharField(
        label=_("Reviewed results TSV path"),
        max_length=1024,
        widget=forms.TextInput(
            attrs={
                "class": "form-control tp-ui-control",
                "placeholder": "/app/targetpathogenweb/imports/Klebsiella/results_table.tsv",
            }
        ),
    )
    structures_dir = forms.CharField(
        label=_("Extracted structures directory"),
        max_length=1024,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control tp-ui-control",
                "placeholder": "/app/targetpathogenweb/imports/Klebsiella/structures",
            }
        ),
    )
    datadir = forms.CharField(
        label=_("TPW data directory"),
        max_length=1024,
        initial="/app/targetpathogenweb/data",
        widget=forms.TextInput(attrs={"class": "form-control tp-ui-control"}),
    )
    overwrite = forms.BooleanField(
        label=_("Overwrite existing values"),
        required=False,
        initial=True,
    )

    def clean(self):
        cleaned = super().clean()
        for field in ("genome_name", "results_tsv", "structures_dir", "datadir"):
            if field in cleaned and cleaned[field]:
                cleaned[field] = str(cleaned[field]).strip()
        return cleaned

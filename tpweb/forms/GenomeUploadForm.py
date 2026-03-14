from django import forms
from django.utils.translation import gettext_lazy as _
import re


class GenomeUploadForm(forms.Form):
    accession = forms.CharField(
        label=_("Genome accession"),
        max_length=128,
        widget=forms.TextInput(
            attrs={
                "class": "form-control tp-ui-control",
                "placeholder": "NZ_AP023069.1",
            }
        ),
    )
    gram = forms.ChoiceField(
        label=_("Gram type"),
        choices=(("n", _("Gram-negative")), ("p", _("Gram-positive"))),
        widget=forms.Select(attrs={"class": "form-control tp-ui-control"}),
    )
    gbk_file = forms.FileField(
        label=_("Compressed GBK file"),
        help_text=_("Upload a `.gbk.gz` file to run the genome pipeline."),
        widget=forms.ClearableFileInput(
            attrs={
                "class": "genome-upload-file-input",
                "accept": ".gbk.gz,.gz,application/gzip",
            }
        ),
    )

    def clean_accession(self):
        accession = str(self.cleaned_data.get("accession") or "").strip()
        if not accession:
            raise forms.ValidationError(_("Provide a genome accession."))
        if not re.fullmatch(r"[A-Za-z0-9._-]+", accession):
            raise forms.ValidationError(
                _("Use only letters, numbers, dots, underscores, or hyphens in the accession.")
            )
        return accession

    def clean_gbk_file(self):
        gbk_file = self.cleaned_data.get("gbk_file")
        filename = getattr(gbk_file, "name", "")
        if not filename.endswith(".gbk.gz"):
            raise forms.ValidationError(_("The genome file must end with `.gbk.gz`."))
        return gbk_file

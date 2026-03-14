import re

from django import forms
from django.utils.translation import gettext_lazy as _

from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from tpweb.services.score_params import (
    visible_score_param_options_queryset,
    visible_score_params_queryset,
)


ACRONYM_TOKENS = {
    "deg": "DEG",
    "ppi": "PPI",
    "dna": "DNA",
    "rna": "RNA",
    "p2rank": "P2RANK",
    "fpocket": "FPocket",
    "id": "ID",
}

TOKEN_REPLACEMENTS = {
    "offtarget": "Off-target",
}

LOWER_CONNECTORS = {"and", "or", "of", "in", "on", "to", "for", "with", "without", "by"}
EXACT_REPLACEMENTS = {
    "human_offtarget": "Human off-target",
    "gut_microbiome_offtarget": "Gut microbiome off-target",
    "hit_in_deg": "Hit in DEG",
    "no_hit": "No hit",
}


def humanize_identifier(value):
    text = str(value or "").strip()
    if not text:
        return ""
    exact_replacement = EXACT_REPLACEMENTS.get(text.lower())
    if exact_replacement:
        return exact_replacement
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split(" ")
    human_tokens = []
    for idx, token in enumerate(tokens):
        token_l = token.lower()
        if token_l in ACRONYM_TOKENS:
            human_tokens.append(ACRONYM_TOKENS[token_l])
            continue
        if token_l in TOKEN_REPLACEMENTS:
            human_tokens.append(TOKEN_REPLACEMENTS[token_l])
            continue
        if idx > 0 and token_l in LOWER_CONNECTORS:
            human_tokens.append(token_l)
            continue
        human_tokens.append(token.capitalize())
    return " ".join(human_tokens)


class HumanizedModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        if hasattr(obj, "name"):
            return humanize_identifier(obj.name)
        return super().label_from_instance(obj)


class ParameterForm(forms.Form):
    param = HumanizedModelChoiceField(
        queryset=ScoreParam.objects.none(),
        empty_label=_("Select parameter..."),
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "hx-get": "../load_options/",
                "hx-target": "#id_options",
                "hx-swap": "innerHTML",
                "hx-trigger": "change",
            }
        ),
    )
    options = HumanizedModelChoiceField(
        queryset=ScoreParamOptions.objects.none(),
        empty_label=_("Select value..."),
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["param"].label = _("Parameter")
        self.fields["options"].label = _("Value")
        self.fields["param"].queryset = visible_score_params_queryset(user)
        if "param" in self.data:
            try:
                param_id = int(self.data.get("param"))
            except (TypeError, ValueError):
                param_id = None
            if param_id:
                self.fields["options"].queryset = visible_score_param_options_queryset(
                    user, param_id
                )

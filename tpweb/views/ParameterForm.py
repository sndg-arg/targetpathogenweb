import re

from django import forms
from django.utils.translation import gettext_lazy as _

from tpweb.models.ScoreParam import ScoreParamOptions
from tpweb.services.score_param_types import score_param_kind
from tpweb.services.score_params import (
    visible_score_param_options_queryset,
    visible_score_params_queryset,
)


SPECIAL_PARAM_STRUCTURE = "__structure__"
SPECIAL_PARAM_EC_NUMBER = "__ec_number__"
SPECIAL_PARAM_GO_TERM = "__go_term__"

SPECIAL_STRUCTURE_CHOICES = (
    ("experimental", _("Experimental")),
    ("alphafold", _("AlphaFold")),
    ("none", _("No structure")),
)


ACRONYM_TOKENS = {
    "deg": "DEG",
    "ppi": "PPI",
    "dna": "DNA",
    "rna": "RNA",
    "p2rank": "P2RANK",
    "fpocket": "FPocket",
    "alphafold": "AlphaFold",
    "id": "ID",
    "ec": "EC",
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
    "ec_number": "EC number",
    "go_term": "GO term",
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
    param = forms.ChoiceField(
        choices=(),
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
    options = forms.ChoiceField(
        choices=(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    text_value = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": _("e.g. 2.7 or GO:0005829"),
            }
        ),
    )
    numeric_operation = forms.ChoiceField(
        required=False,
        choices=(
            (">=", ">="),
            ("<=", "<="),
            ("between", _("between")),
        ),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    numeric_value = forms.FloatField(
        required=False,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "any",
                "placeholder": _("Enter value..."),
            }
        ),
    )
    numeric_value_max = forms.FloatField(
        required=False,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "any",
                "placeholder": _("Max value"),
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["param"].label = _("Parameter")
        self.fields["options"].label = _("Value")
        self.fields["text_value"].label = _("Value")
        self.fields["numeric_operation"].label = _("Operator")
        self.fields["numeric_value"].label = _("Value")
        self.fields["numeric_value_max"].label = _("Max value")

        score_params = list(visible_score_params_queryset(user))
        self.score_params_by_id = {str(score_param.id): score_param for score_param in score_params}
        self.fields["param"].choices = [
            ("", _("Select parameter...")),
            (SPECIAL_PARAM_STRUCTURE, _("Structure")),
            (SPECIAL_PARAM_EC_NUMBER, _("EC number")),
            (SPECIAL_PARAM_GO_TERM, _("GO term")),
            *[(str(score_param.id), humanize_identifier(score_param.name)) for score_param in score_params],
        ]

        param_raw = str(self.data.get("param") or "").strip()
        self.fields["options"].choices = [("", _("Select value..."))]

        if param_raw == SPECIAL_PARAM_STRUCTURE:
            self.fields["options"].choices = [("", _("Select value...")), *SPECIAL_STRUCTURE_CHOICES]
        elif param_raw in self.score_params_by_id:
            score_param = self.score_params_by_id[param_raw]
            if score_param_kind(score_param) == "categorical":
                options = visible_score_param_options_queryset(user, score_param.id)
                self.fields["options"].choices = [
                    ("", _("Select value...")),
                    *[(str(option.id), humanize_identifier(option.name)) for option in options],
                ]

    def clean(self):
        cleaned_data = super().clean()
        param_value = str(cleaned_data.get("param") or "").strip()
        if not param_value:
            return cleaned_data

        if param_value == SPECIAL_PARAM_STRUCTURE:
            option_value = str(cleaned_data.get("options") or "").strip()
            valid_values = {choice[0] for choice in SPECIAL_STRUCTURE_CHOICES}
            if option_value not in valid_values:
                self.add_error("options", _("Select a structure value."))
            return cleaned_data

        if param_value in {SPECIAL_PARAM_EC_NUMBER, SPECIAL_PARAM_GO_TERM}:
            text_value = str(cleaned_data.get("text_value") or "").strip()
            if not text_value:
                if param_value == SPECIAL_PARAM_EC_NUMBER:
                    self.add_error("text_value", _("Enter an EC number or prefix."))
                else:
                    self.add_error("text_value", _("Enter a GO accession."))
            else:
                cleaned_data["text_value"] = text_value
            return cleaned_data

        score_param = self.score_params_by_id.get(param_value)
        if score_param is None:
            self.add_error("param", _("Select a valid parameter."))
            return cleaned_data

        cleaned_data["resolved_param"] = score_param
        param_kind = score_param_kind(score_param)
        if param_kind == "categorical":
            option_id = str(cleaned_data.get("options") or "").strip()
            if not option_id:
                self.add_error("options", _("Select a categorical value."))
                return cleaned_data
            selected_option = visible_score_param_options_queryset(self.user, score_param.id).filter(id=option_id).first()
            if selected_option is None:
                self.add_error("options", _("Select a valid value."))
                return cleaned_data
            cleaned_data["resolved_option"] = selected_option
            return cleaned_data

        operation = cleaned_data.get("numeric_operation")
        value = cleaned_data.get("numeric_value")
        value_max = cleaned_data.get("numeric_value_max")

        if not operation:
            self.add_error("numeric_operation", _("Select an operator."))
        if value is None:
            self.add_error("numeric_value", _("Enter a numeric value."))
        if operation == "between":
            if value_max is None:
                self.add_error("numeric_value_max", _("Enter the upper value."))
            elif value is not None and value_max < value:
                self.add_error("numeric_value_max", _("Upper value must be greater than or equal to the lower value."))
        return cleaned_data

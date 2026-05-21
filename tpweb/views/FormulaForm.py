from django import forms

_CTRL = "form-control tp-ui-control"


class FormulaForm(forms.Form):
    formula_name = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": _CTRL,
            "placeholder": "e.g. My target score",
            "autocomplete": "off",
        }),
    )
    expression = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": f"{_CTRL} formula-expression-input",
            "rows": "5",
            "placeholder": "e.g.  0.6 * druggability + 2 * hit_in_deg_y - 0.02 * human_identity",
            "spellcheck": "false",
            "autocomplete": "off",
            "id": "id_expression",
        }),
    )

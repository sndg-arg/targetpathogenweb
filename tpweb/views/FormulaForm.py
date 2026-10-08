from django import forms

from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.score_params import visible_score_params_queryset
from tpweb.services.visibility_settings import VISIBILITY_PRIVATE, FORMULA_VISIBILITY_CHOICES

_CTRL = "form-control tp-ui-control"


class FormulaForm(forms.Form):
    param = forms.ModelChoiceField(
        queryset=ScoreParam.objects.none(),
        required=False,
    )
    formula_name = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": _CTRL,
                "placeholder": "e.g. My target score",
                "autocomplete": "off",
            }
        ),
    )
    expression = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": f"{_CTRL} formula-expression-input",
                "rows": "5",
                "placeholder": "e.g.  0.6 * druggability + 2 * hit_in_deg_y - 0.02 * human_identity",
                "spellcheck": "false",
                "autocomplete": "off",
                "id": "id_expression",
            }
        ),
    )
    # Who else can see/use this formula -- private by default, changeable
    # later from the Settings page (tpweb/views/SettingsView.py) without
    # needing to recreate it.
    visibility = forms.ChoiceField(
        choices=FORMULA_VISIBILITY_CHOICES,
        initial=VISIBILITY_PRIVATE,
        required=False,
        widget=forms.Select(attrs={"class": _CTRL}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["param"].queryset = visible_score_params_queryset(user)

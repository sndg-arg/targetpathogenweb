from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from django import forms
from tpweb.services.score_params import (
    visible_score_param_options_queryset,
    visible_score_params_queryset,
)
from tpweb.views.ParameterForm import HumanizedModelChoiceField

class FormulaForm(forms.Form):
    param = HumanizedModelChoiceField(
        queryset=ScoreParam.objects.none(),
        empty_label="Select parameter...",
        widget=forms.Select(attrs={"hx-get": "../load_options/", "hx-target": "#id_options"}),
    )
    options = HumanizedModelChoiceField(
        queryset=ScoreParamOptions.objects.none(),
        empty_label="Select value...",
    )
    coefficient = forms.FloatField()
    new_formula_name = forms.CharField()

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["param"].label = "Param"
        self.fields["options"].label = "Options"
        self.fields["coefficient"].label = "Coefficient"
        self.fields["new_formula_name"].label = "New formula name"
        self.fields["param"].queryset = visible_score_params_queryset(user)
        if "param" in self.data:
            try:
                param_id = int(self.data.get("param"))
            except (TypeError, ValueError):
                param_id = None
            if param_id:
                self.fields["options"].queryset = visible_score_param_options_queryset(user, param_id)

from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
from django import forms

class ParameterForm(forms.Form):
    param = forms.ModelChoiceField(queryset = ScoreParam.objects.all(),
                                   widget=forms.Select(attrs={"hx-get": "../load_options/", "hx-target": "#id_options"}))
    options = forms.ModelChoiceField(queryset = ScoreParamOptions.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(self.data)
        if "param" in self.data:
            param_id = int(self.data.get("param"))
            self.fields["options"].queryset = ScoreParamOptions.objects.filter(score_param_id=param_id)

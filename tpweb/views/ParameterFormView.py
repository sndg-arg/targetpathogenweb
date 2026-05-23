from django.shortcuts import render

from tpweb.views.ParameterForm import humanize_identifier
from tpweb.services.score_params import visible_score_param_options_queryset


def load_options(request):
    """HTMX endpoint that returns ScoreParam option markup for cascading selects.

    Used by FormulaForm to populate the value dropdown when a parameter is picked.
    """
    param_id = request.GET.get("param")
    options = []
    if param_id:
        options = [
            {"id": option.id, "label": humanize_identifier(option.name) or option.name}
            for option in visible_score_param_options_queryset(request.user, param_id)
        ]
    return render(request, "search/parameter_options.html", {"options": options})

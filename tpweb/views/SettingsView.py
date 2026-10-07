from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.models.RestrictedGenome import RestrictedGenome
from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.genome_workspace import display_genome_name
from tpweb.services.genomes import set_genome_restricted
from tpweb.services.visibility_settings import (
    FORMULA_VISIBILITY_CHOICES,
    PARAM_VISIBILITY_CHOICES,
    all_shareable_custom_params,
    all_shareable_formulas,
    custom_params_owned_by,
    formula_visibility,
    formulas_owned_by,
    param_visibility,
    set_formula_visibility,
    set_param_visibility,
)
from tpweb.views.mixins import PermissionLockedMixin


class SettingsView(PermissionLockedMixin, View):
    """Owner-controlled visibility for scoring formulas and custom params,
    plus (superuser-only) a supervising overview of every user's items and
    the existing restricted-genomes list. Any approved user who can manage
    formulas/custom params can reach this page -- that's every role today
    (see tpweb.services.user_permissions.PROFILE_PRESETS) -- to decide
    their own items' visibility; a superuser can additionally override
    anyone's."""

    template_name = "users/settings.html"
    page_title = "Settings"
    locked_message = "Ask the site owner to grant access to scoring formulas or custom params."

    def test_func(self):
        user = self.request.user
        return user.has_perm("tpweb.can_manage_formulas") or user.has_perm(
            "tpweb.can_manage_custom_params"
        )

    def _rows(self, formulas, params):
        formula_rows = [
            {"obj": formula, "visibility": formula_visibility(formula)} for formula in formulas
        ]
        param_rows = [{"obj": param, "visibility": param_visibility(param)} for param in params]
        return formula_rows, param_rows

    def get(self, request, *args, **kwargs):
        my_formula_rows, my_param_rows = self._rows(
            formulas_owned_by(request.user), custom_params_owned_by(request.user)
        )
        context = {
            "my_formula_rows": my_formula_rows,
            "my_param_rows": my_param_rows,
            "formula_visibility_choices": FORMULA_VISIBILITY_CHOICES,
            "param_visibility_choices": PARAM_VISIBILITY_CHOICES,
            "is_superuser_view": request.user.is_superuser,
        }
        if request.user.is_superuser:
            all_formula_rows, all_param_rows = self._rows(
                all_shareable_formulas(), all_shareable_custom_params()
            )
            context.update(
                {
                    "all_formula_rows": all_formula_rows,
                    "all_param_rows": all_param_rows,
                    "restricted_genomes": [
                        {"obj": rg, "label": display_genome_name(rg.genome_name)}
                        for rg in RestrictedGenome.objects.select_related("restricted_by")
                    ],
                }
            )
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "set_formula_visibility":
            formula = ScoreFormula.objects.filter(pk=request.POST.get("formula_id")).first()
            visibility = request.POST.get("visibility")
            if formula is None or not set_formula_visibility(formula, request.user, visibility):
                messages.error(request, "Couldn't update that formula's visibility.")
            else:
                messages.success(request, f"Updated visibility for {formula.name}.")
        elif action == "set_param_visibility":
            param = ScoreParam.objects.filter(pk=request.POST.get("param_id")).first()
            visibility = request.POST.get("visibility")
            if param is None or not set_param_visibility(param, request.user, visibility):
                messages.error(request, "Couldn't update that custom param's visibility.")
            else:
                messages.success(request, f"Updated visibility for {param.name}.")
        elif action == "unrestrict_genome" and request.user.is_superuser:
            genome_name = request.POST.get("genome_name", "").strip()
            if genome_name:
                set_genome_restricted(genome_name, False, request.user)
                messages.success(request, f"{display_genome_name(genome_name)} is public again.")
        else:
            messages.error(request, "Unknown action.")
        return redirect(reverse("tpwebapp:settings"))

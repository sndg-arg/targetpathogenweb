from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.models.RestrictedGenome import RestrictedGenome
from tpweb.models.ScoreFormula import ScoreFormula
from tpweb.models.ScoreParam import ScoreParam
from tpweb.services.custom_param_sharing import (
    column_rows,
    delete_column,
    update_column_visibility,
)
from tpweb.services.genome_workspace import display_genome_name
from tpweb.services.genomes import set_genome_restricted
from tpweb.services.visibility_settings import (
    FORMULA_VISIBILITY_CHOICES,
    all_shareable_custom_params,
    all_shareable_formulas,
    custom_params_owned_by,
    formula_visibility,
    formulas_owned_by,
    set_formula_visibility,
)
from tpweb.views.mixins import PermissionLockedMixin


def _group_by_owner(formula_rows, param_rows):
    """Admin overview: one collapsible block per user instead of one long
    table of every user's items."""
    groups = {}
    for kind, rows in (("formulas", formula_rows), ("columns", param_rows)):
        for row in rows:
            owner = row["obj"].user
            group = groups.setdefault(
                owner.pk,
                {
                    "label": (owner.name or "").strip() or owner.get_username(),
                    "formulas": [],
                    "columns": [],
                },
            )
            group[kind].append(row)
    for group in groups.values():
        group["shared_count"] = sum(
            1 for row in group["formulas"] + group["columns"] if row["visibility"] != "private"
        )
    return sorted(groups.values(), key=lambda group: group["label"].casefold())


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
        return formula_rows, column_rows(params)

    def get(self, request, *args, **kwargs):
        my_formula_rows, my_param_rows = self._rows(
            formulas_owned_by(request.user), custom_params_owned_by(request.user)
        )
        context = {
            "my_formula_rows": my_formula_rows,
            "my_param_rows": my_param_rows,
            "formula_visibility_choices": FORMULA_VISIBILITY_CHOICES,
            "is_superuser_view": request.user.is_superuser,
        }
        if request.user.is_superuser:
            all_formula_rows, all_param_rows = self._rows(
                all_shareable_formulas(), all_shareable_custom_params()
            )
            shared_formula_rows = [
                row for row in all_formula_rows if row["visibility"] != "private"
            ]
            shared_param_rows = [row for row in all_param_rows if row["visibility"] != "private"]
            context.update(
                {
                    "shared_formula_rows": shared_formula_rows,
                    "shared_param_rows": shared_param_rows,
                    "shared_total": len(shared_formula_rows) + len(shared_param_rows),
                    "user_groups": _group_by_owner(all_formula_rows, all_param_rows),
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
            genome_name = request.POST.get("genome_name", "").strip()
            visibility = request.POST.get("visibility")
            if param is None or not update_column_visibility(
                param, genome_name, request.user, visibility
            ):
                messages.error(request, "Couldn't update that column's visibility.")
            else:
                messages.success(
                    request,
                    f"Updated who can see {param.name} on {display_genome_name(genome_name)}.",
                )
        elif action == "delete_param":
            param = ScoreParam.objects.filter(pk=request.POST.get("param_id")).first()
            genome_name = request.POST.get("genome_name", "").strip()
            name = param.name if param else ""
            if param is None or not delete_column(param, genome_name, request.user):
                messages.error(request, "Couldn't delete that column.")
            else:
                messages.success(
                    request, f"Deleted {name} from {display_genome_name(genome_name)}."
                )
        elif action == "unrestrict_genome" and request.user.is_superuser:
            genome_name = request.POST.get("genome_name", "").strip()
            if genome_name:
                set_genome_restricted(genome_name, False, request.user)
                messages.success(request, f"{display_genome_name(genome_name)} is public again.")
        else:
            messages.error(request, "Unknown action.")
        return redirect(reverse("tpwebapp:settings"))

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
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
    delete_own_formula,
    formulas_owned_by,
    set_formula_visibility,
)
from tpweb.views.mixins import PermissionLockedMixin


def _researcher_summaries(formula_rows, param_rows):
    """Admin overview, one entry per researcher: how many formulas and
    columns they have, and only the items they chose to share. "Only me"
    items are counted, never named -- not even an admin sees them."""
    groups = {}
    for kind, rows in (("formula", formula_rows), ("column", param_rows)):
        for row in rows:
            owner = row["obj"].user
            group = groups.setdefault(
                owner.pk,
                {
                    "label": (owner.name or "").strip() or owner.get_username(),
                    "formulas": 0,
                    "columns": 0,
                    "private": 0,
                    "private_formulas": 0,
                    "private_columns": 0,
                    "shared": [],
                },
            )
            group[f"{kind}s"] += 1
            if row["visibility"] == "private":
                group["private"] += 1
                group[f"private_{kind}s"] += 1
            else:
                group["shared"].append({"row": row, "kind": kind})
    return sorted(groups.values(), key=lambda group: group["label"].casefold())


def _search_text(item):
    """Name, genome or researcher of a Settings list item, for the search box."""
    obj = item.get("obj")
    parts = [item.get("label", ""), item.get("genome_label", ""), getattr(obj, "name", "") or ""]
    return " ".join(str(part) for part in parts).casefold()


class SettingsView(PermissionLockedMixin, View):
    """Owner-controlled visibility for scoring formulas and custom params,
    plus (superuser-only) a per-researcher summary and the restricted-genomes
    list. Any approved user who can manage formulas/custom params can reach
    this page -- that's every role today (see
    tpweb.services.user_permissions.PROFILE_PRESETS). A superuser sees only
    what researchers shared, read-only; "Only me" items stay with their owner."""

    template_name = "users/settings.html"
    page_title = "Settings"
    locked_message = "Your account can't create scoring formulas or upload data yet."

    def test_func(self):
        user = self.request.user
        return user.has_perm("tpweb.can_manage_formulas") or user.has_perm(
            "tpweb.can_manage_custom_params"
        )

    def _rows(self, formulas, params):
        labels = dict(FORMULA_VISIBILITY_CHOICES)
        formula_rows = []
        for formula in formulas:
            visibility = formula_visibility(formula)
            formula_rows.append(
                {"obj": formula, "visibility": visibility, "visibility_label": labels[visibility]}
            )
        return formula_rows, column_rows(params)

    def get(self, request, *args, **kwargs):
        my_formula_rows, my_param_rows = self._rows(
            formulas_owned_by(request.user), custom_params_owned_by(request.user)
        )
        context = {"formula_visibility_choices": FORMULA_VISIBILITY_CHOICES}
        # The side nav prints a heading whenever "group" changes.
        collections = {"formulas": my_formula_rows, "data": my_param_rows}
        labels = [
            ("formulas", _("Scoring formulas"), _("Your work")),
            ("data", _("Uploaded data"), _("Your work")),
        ]
        if request.user.is_superuser:
            collections.update(
                users=_researcher_summaries(
                    *self._rows(all_shareable_formulas(), all_shareable_custom_params())
                ),
                genomes=[
                    {"obj": rg, "label": display_genome_name(rg.genome_name)}
                    for rg in RestrictedGenome.objects.select_related("restricted_by")
                ],
            )
            labels += [
                ("users", _("Researchers"), _("Administration")),
                ("genomes", _("Restricted genomes"), _("Administration")),
            ]
        sections = [
            {"key": key, "label": label, "group": group, "count": len(collections[key])}
            for key, label, group in labels
        ]
        active_section = request.GET.get("section", "formulas")
        if active_section not in collections:
            active_section = "formulas"
        items = collections[active_section]
        search_query = request.GET.get("q", "").strip()
        if search_query:
            needle = search_query.casefold()
            items = [item for item in items if needle in _search_text(item)]
        page = Paginator(items, 20).get_page(request.GET.get("page"))
        query = {"section": active_section}
        if search_query:
            query["q"] = search_query
        context.update(
            search_query=search_query,
            settings_sections=sections,
            active_section=active_section,
            page_obj=page,
            page_numbers=page.paginator.get_elided_page_range(
                page.number, on_each_side=1, on_ends=1
            ),
            pagination_query=urlencode(query),
            settings_return_query=urlencode({**query, "page": page.number}),
        )
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        ok, message = self._apply(request)
        # settings.js saves in place and only needs the outcome.
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": ok, "message": message}, status=200 if ok else 400)
        (messages.success if ok else messages.error)(request, message)
        query = {key: request.GET[key] for key in ("section", "page", "q") if key in request.GET}
        url = reverse("tpwebapp:settings")
        return redirect(f"{url}?{urlencode(query)}" if query else url)

    def _apply(self, request):
        """Run the posted action; returns (ok, message)."""
        action = request.POST.get("action")
        if action == "set_formula_visibility":
            formula = ScoreFormula.objects.filter(pk=request.POST.get("formula_id")).first()
            visibility = request.POST.get("visibility")
            if formula is None or not set_formula_visibility(formula, request.user, visibility):
                return False, "Couldn't update that formula's visibility."
            return True, f"Updated visibility for {formula.name}."
        if action == "delete_formula":
            formula = ScoreFormula.objects.filter(pk=request.POST.get("formula_id")).first()
            name = formula.name if formula else ""
            if formula is None or not delete_own_formula(formula, request.user):
                return False, "Couldn't delete that formula."
            return True, f"Deleted {name}."
        if action == "set_param_visibility":
            param = ScoreParam.objects.filter(pk=request.POST.get("param_id")).first()
            genome_name = request.POST.get("genome_name", "").strip()
            visibility = request.POST.get("visibility")
            if param is None or not update_column_visibility(
                param, genome_name, request.user, visibility
            ):
                return False, "Couldn't update that column's visibility."
            return True, f"Updated who can see {param.name} on {display_genome_name(genome_name)}."
        if action == "delete_param":
            param = ScoreParam.objects.filter(pk=request.POST.get("param_id")).first()
            genome_name = request.POST.get("genome_name", "").strip()
            name = param.name if param else ""
            if param is None or not delete_column(param, genome_name, request.user):
                return False, "Couldn't delete that column."
            return True, f"Deleted {name} from {display_genome_name(genome_name)}."
        if action == "unrestrict_genome" and request.user.is_superuser:
            genome_name = request.POST.get("genome_name", "").strip()
            if not genome_name:
                return False, "Couldn't unrestrict that genome."
            set_genome_restricted(genome_name, False, request.user)
            return True, f"{display_genome_name(genome_name)} is public again."
        return False, "Unknown action."

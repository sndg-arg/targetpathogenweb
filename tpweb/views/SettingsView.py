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
                    "id": owner.pk,
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


def _search_text(item):
    """Name, genome and owner of any Settings list item, for the search box."""
    row = item.get("row", item)
    obj = row.get("obj")
    owner = getattr(obj, "user", None)
    parts = [
        row.get("label", ""),
        row.get("genome_label", ""),
        getattr(obj, "name", "") or "",
        getattr(owner, "name", "") or "",
    ]
    return " ".join(str(part) for part in parts).casefold()


class SettingsView(PermissionLockedMixin, View):
    """Owner-controlled visibility for scoring formulas and custom params,
    plus (superuser-only) a supervising overview of every user's items and
    the existing restricted-genomes list. Any approved user who can manage
    formulas/custom params can reach this page -- that's every role today
    (see tpweb.services.user_permissions.PROFILE_PRESETS) -- to decide
    their own items' visibility. A superuser sees everyone's items here
    read-only -- only the owner can change who sees them."""

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
        context = {
            "my_formula_rows": my_formula_rows,
            "my_param_rows": my_param_rows,
            "formula_visibility_choices": FORMULA_VISIBILITY_CHOICES,
            "is_superuser_view": request.user.is_superuser,
        }
        # The side nav prints a heading whenever "group" changes.
        sections = [
            {"key": key, "label": label, "group": _("Your work"), "count": len(rows)}
            for key, label, rows in (
                ("formulas", _("Scoring formulas"), my_formula_rows),
                ("data", _("Uploaded data"), my_param_rows),
            )
        ]
        collections = {"formulas": my_formula_rows, "data": my_param_rows}
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
            collections.update(
                shared=[
                    {"row": row, "kind": kind}
                    for kind, rows in (
                        ("formula", shared_formula_rows),
                        ("column", shared_param_rows),
                    )
                    for row in rows
                ],
                users=context["user_groups"],
                genomes=context["restricted_genomes"],
            )
            sections.extend(
                {
                    "key": key,
                    "label": label,
                    "group": _("Administration"),
                    "count": len(collections[key]),
                }
                for key, label in (
                    ("shared", _("Shared items")),
                    ("users", _("Researchers")),
                    ("genomes", _("Restricted genomes")),
                )
            )
        active_section = request.GET.get("section", "formulas")
        if active_section not in collections:
            active_section = "formulas"
        # The owner directory and the selected owner's items paginate separately.
        selected_owner = None
        if active_section == "users":
            selected_owner = next(
                (
                    group
                    for group in context["user_groups"]
                    if str(group["id"]) == request.GET.get("owner")
                ),
                None,
            )
            if selected_owner:
                collections["users"] = [
                    {"row": row, "kind": kind}
                    for kind, rows in (
                        ("formula", selected_owner["formulas"]),
                        ("column", selected_owner["columns"]),
                    )
                    for row in rows
                ]
        items = collections[active_section]
        search_query = request.GET.get("q", "").strip()
        if search_query:
            needle = search_query.casefold()
            items = [item for item in items if needle in _search_text(item)]
        page = Paginator(items, 20).get_page(request.GET.get("page"))
        query = {"section": active_section}
        if selected_owner:
            query["owner"] = selected_owner["id"]
        if search_query:
            query["q"] = search_query
        context.update(
            search_query=search_query,
            settings_sections=sections,
            active_section=active_section,
            selected_owner=selected_owner,
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
        query = {
            key: request.GET[key] for key in ("section", "page", "owner", "q") if key in request.GET
        }
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

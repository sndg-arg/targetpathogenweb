from importlib import import_module
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

settings_view = import_module("tpweb.views.SettingsView")


class SettingsNavigationTests(SimpleTestCase):
    def get_context(self, query=None, *, admin=False, formulas=None, columns=None):
        request = RequestFactory().get("/settings/", query or {})
        request.user = SimpleNamespace(is_superuser=admin)
        rows = (formulas or [], columns or [])
        with (
            mock.patch.multiple(
                settings_view,
                formulas_owned_by=mock.DEFAULT,
                custom_params_owned_by=mock.DEFAULT,
                all_shareable_formulas=mock.DEFAULT,
                all_shareable_custom_params=mock.DEFAULT,
                RestrictedGenome=mock.DEFAULT,
                render=mock.DEFAULT,
            ) as patched,
            mock.patch.object(settings_view.SettingsView, "_rows", return_value=rows),
        ):
            patched["RestrictedGenome"].objects.select_related.return_value = []
            settings_view.SettingsView().get(request)
            return patched["render"].call_args.args[2]

    def test_personal_lists_paginate_and_keep_total_counts(self):
        context = self.get_context({"section": "data", "page": "2"}, columns=list(range(43)))
        self.assertEqual(list(context["page_obj"]), list(range(20, 40)))
        self.assertEqual(context["settings_sections"][1]["count"], 43)
        self.assertEqual(context["settings_return_query"], "section=data&page=2")

    def test_admin_sections_cannot_be_selected_by_regular_users(self):
        for section in ("users", "genomes", "unknown"):
            with self.subTest(section=section):
                context = self.get_context({"section": section}, formulas=[1])
                self.assertEqual(context["active_section"], "formulas")
                self.assertEqual(len(context["settings_sections"]), 2)
                self.assertEqual(list(context["page_obj"]), [1])

    def test_invalid_and_outdated_page_numbers_are_safe(self):
        for number, expected in (("invalid", 1), ("999", 3), ("0", 3)):
            with self.subTest(page=number):
                context = self.get_context({"page": number}, formulas=list(range(41)))
                self.assertEqual(context["page_obj"].number, expected)

    def test_researchers_show_counts_and_shared_items_but_never_private_ones(self):
        owner = SimpleNamespace(pk=7, name="Researcher")
        secret = SimpleNamespace(name="Secret score", user=owner)
        shared = SimpleNamespace(name="Shared score", user=owner)
        context = self.get_context(
            {"section": "users"},
            admin=True,
            formulas=[
                {"obj": secret, "visibility": "private"},
                {"obj": shared, "visibility": "public"},
            ],
            columns=[{"obj": secret, "visibility": "private"}],
        )
        (person,) = context["page_obj"]
        self.assertEqual((person["formulas"], person["columns"], person["private"]), (2, 1, 2))
        self.assertEqual([item["row"]["obj"] for item in person["shared"]], [shared])
        self.assertNotIn("Secret score", repr(context))

    def test_researchers_search_by_name(self):
        rows = [
            {"obj": SimpleNamespace(user=SimpleNamespace(pk=pk, name=name)), "visibility": "public"}
            for pk, name in ((1, "Ana"), (2, "Bruno"))
        ]
        context = self.get_context({"section": "users", "q": "bru"}, admin=True, formulas=rows)
        self.assertEqual([person["label"] for person in context["page_obj"]], ["Bruno"])

    def test_search_filters_by_name_or_genome_and_stays_in_links(self):
        owner = SimpleNamespace(pk=7, name="Researcher")
        columns = [
            {"obj": SimpleNamespace(name="Essentiality", user=owner), "genome_label": "KpATCC"},
            {"obj": SimpleNamespace(name="Expression", user=owner), "genome_label": "Mtb H37Rv"},
        ]
        for term, expected in (("essen", ["Essentiality"]), ("h37", ["Expression"]), ("", None)):
            with self.subTest(term=term):
                context = self.get_context({"section": "data", "q": term}, columns=columns)
                names = [row["obj"].name for row in context["page_obj"]]
                self.assertEqual(names, expected or ["Essentiality", "Expression"])
        context = self.get_context({"section": "data", "q": "essen"}, columns=columns)
        self.assertEqual(context["pagination_query"], "section=data&q=essen")

    def test_post_redirect_preserves_section_page_and_search(self):
        request = RequestFactory().post("/settings/?section=data&page=2&q=kp&ignored=value")
        with (
            mock.patch.object(settings_view.messages, "error"),
            mock.patch.object(settings_view, "reverse", return_value="/settings/"),
        ):
            response = settings_view.SettingsView().post(request)
        self.assertEqual(response.url, "/settings/?section=data&page=2&q=kp")

    def test_ajax_post_answers_json_instead_of_redirecting(self):
        request = RequestFactory().post(
            "/settings/?section=data", {"action": "nope"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        response = settings_view.SettingsView().post(request)
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"ok": False, "message": "Unknown action."})


class AdminHidesResearcherDataTests(SimpleTestCase):
    def test_every_score_admin_excludes_researcher_owned_rows(self):
        from django.contrib import admin

        from tpweb.admin.private_data import HideResearcherDataMixin
        from tpweb.models.CustomParamShare import CustomParamShare
        from tpweb.models.ScoreFormula import ScoreFormula, ScoreFormulaParam
        from tpweb.models.ScoreParam import ScoreParam, ScoreParamOptions
        from tpweb.models.ScoreParamValue import ScoreParamValue

        for model in (
            ScoreParam,
            ScoreParamOptions,
            ScoreParamValue,
            CustomParamShare,
            ScoreFormula,
            ScoreFormulaParam,
        ):
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertIsInstance(model_admin, HideResearcherDataMixin)
                where = str(model_admin.get_queryset(RequestFactory().get("/")).query.where)
                self.assertIn("NOT", where)

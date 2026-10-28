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
        for section in ("shared", "users", "genomes", "unknown"):
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

    def test_owner_items_are_paginated_and_keep_owner_in_links(self):
        owner = SimpleNamespace(pk=7, name="Researcher")
        formulas = [
            {"obj": SimpleNamespace(user=owner), "visibility": "private"} for _ in range(23)
        ]
        context = self.get_context(
            {"section": "users", "owner": "7", "page": "2"},
            admin=True,
            formulas=formulas,
        )
        self.assertEqual(context["selected_owner"]["id"], 7)
        self.assertEqual(len(context["page_obj"]), 3)
        self.assertEqual(context["page_obj"].paginator.count, 23)
        self.assertEqual(context["pagination_query"], "section=users&owner=7")
        self.assertEqual(context["page_obj"][0]["kind"], "formula")

    def test_shared_items_exclude_private_rows_and_include_both_types(self):
        owner = SimpleNamespace(pk=7, name="Researcher")
        obj = SimpleNamespace(user=owner)
        context = self.get_context(
            {"section": "shared"},
            admin=True,
            formulas=[
                {"obj": obj, "visibility": "private"},
                {"obj": obj, "visibility": "public"},
            ],
            columns=[{"obj": obj, "visibility": "project"}],
        )
        self.assertEqual(context["page_obj"].paginator.count, 2)
        self.assertEqual([item["kind"] for item in context["page_obj"]], ["formula", "column"])

    def test_search_filters_by_name_genome_and_owner_and_stays_in_links(self):
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

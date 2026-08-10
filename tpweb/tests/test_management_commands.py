"""Tests for management commands with no bioseq model dependency -- pure
tpweb models whose schema this test file can read directly, so fixtures
here are built from source, not guessed.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tpweb.models.AgentChatSession import AgentChatSession
from tpweb.management.commands.fetch_ec_nomenclature import (
    build_hierarchy_labels,
    parse_enzclass_txt,
    parse_enzyme_dat,
)


class ClearOldAgentChatsTests(TestCase):
    def _create_session(self, key, days_old):
        session = AgentChatSession.objects.create(session_key=key, history_json=[])
        # updated_at is auto_now=True, so Model.save() always overwrites it --
        # backdate via a queryset .update(), which bypasses auto_now.
        backdated = timezone.now() - timedelta(days=days_old)
        AgentChatSession.objects.filter(pk=session.pk).update(updated_at=backdated)
        return session

    def test_deletes_only_sessions_older_than_retention_window(self):
        self._create_session("old-session", days_old=10)
        self._create_session("recent-session", days_old=1)

        call_command("clear_old_agent_chats", stdout=StringIO())

        remaining = set(AgentChatSession.objects.values_list("session_key", flat=True))
        self.assertEqual(remaining, {"recent-session"})

    def test_dry_run_deletes_nothing(self):
        self._create_session("old-session", days_old=10)

        call_command("clear_old_agent_chats", "--dry-run", stdout=StringIO())

        self.assertTrue(AgentChatSession.objects.filter(session_key="old-session").exists())

    def test_custom_days_argument_overrides_default_ttl(self):
        self._create_session("three-days-old", days_old=3)

        call_command("clear_old_agent_chats", "--days=2", stdout=StringIO())

        self.assertFalse(AgentChatSession.objects.filter(session_key="three-days-old").exists())


class ParseEnzymeDatTests(TestCase):
    """fetch_ec_nomenclature.py rebuilds tpweb/data/ec_hierarchy_labels.json,
    which drives the Annotation Explorer's EC hierarchy -- these pure parsers
    have no DB/network dependency, so get exact fixture control over ExPASy's
    format instead of guessing at real downloaded content."""

    def test_extracts_level_4_enzyme_name_and_strips_trailing_period(self):
        text = "ID   1.1.1.1\nDE   Alcohol dehydrogenase.\n//\n"

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {"1.1.1.1": "Alcohol dehydrogenase"})

    def test_joins_multiline_de_field_with_spaces(self):
        text = "ID   1.1.1.3\nDE   Homoserine\nDE   dehydrogenase.\n//\n"

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {"1.1.1.3": "Homoserine dehydrogenase"})

    def test_skips_transferred_and_deleted_entries(self):
        text = (
            "ID   1.1.1.2\n"
            "DE   Transferred entry: 1.1.1.71.\n"
            "//\n"
            "ID   1.1.1.199\n"
            "DE   Deleted entry.\n"
            "//\n"
        )

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {})


class ParseEnzclassTxtTests(TestCase):
    def test_dash_third_component_is_a_subclass(self):
        text = "1. 1.-.-  Oxidoreductases acting on donors\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {"1.1": "Oxidoreductases acting on donors"})
        self.assertEqual(subsubclass_labels, {})

    def test_numeric_third_component_is_a_subsubclass(self):
        text = "1. 1. 1.-  Acting on the CH-OH group of donors\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {})
        self.assertEqual(subsubclass_labels, {"1.1.1": "Acting on the CH-OH group of donors"})

    def test_non_matching_lines_are_ignored(self):
        text = "This is a comment line, not an EC class entry.\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {})
        self.assertEqual(subsubclass_labels, {})


class BuildHierarchyLabelsTests(TestCase):
    def test_combines_all_levels_under_expected_keys(self):
        result = build_hierarchy_labels(
            enzyme_names={"1.1.1.1": "Alcohol dehydrogenase"},
            subclass_labels={"1.1": "Oxidoreductases acting on donors"},
            subsubclass_labels={"1.1.1": "Acting on the CH-OH group of donors"},
        )

        self.assertEqual(result["enzyme_names"], {"1.1.1.1": "Alcohol dehydrogenase"})
        self.assertEqual(result["subclass_labels"], {"1.1": "Oxidoreductases acting on donors"})
        self.assertIn("class_labels", result)
        self.assertEqual(result["class_labels"]["1"], "Oxidoreductases")

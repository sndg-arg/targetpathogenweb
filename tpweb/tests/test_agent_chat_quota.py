import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from tpweb.models import TPUser
from tpweb.models.AgentChatMessageLog import AgentChatMessageLog
from tpweb.services.agent_chat_quota import (
    ROLE_DAILY_QUOTAS,
    messages_used,
    quota_exceeded,
    quota_for,
    record_message,
)
from tpweb.views.AgentChatView import AgentChatView

User = get_user_model()


def _grant_chat_permission(user):
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="tpweb", codename="can_use_agent_chat")
    )


class AgentChatQuotaServiceTests(TestCase):
    def setUp(self):
        self.basic_user = User.objects.create_user(
            username="quota-basic", password="x", role=TPUser.Role.BASIC
        )
        self.collab_user = User.objects.create_user(
            username="quota-collab", password="x", role=TPUser.Role.GATES_COLLABORATOR
        )
        self.superuser = User.objects.create_user(
            username="quota-super", password="x", is_superuser=True
        )

    def test_quota_for_basic_role_matches_the_configured_constant(self):
        self.assertEqual(quota_for(self.basic_user), ROLE_DAILY_QUOTAS[TPUser.Role.BASIC])

    def test_quota_for_gates_collaborator_is_unlimited(self):
        self.assertIsNone(quota_for(self.collab_user))

    def test_quota_for_superuser_is_unlimited_regardless_of_role(self):
        self.assertIsNone(quota_for(self.superuser))

    def test_quota_exceeded_trips_exactly_at_the_cap(self):
        quota = quota_for(self.basic_user)
        for _ in range(quota - 1):
            record_message(self.basic_user)
        self.assertFalse(quota_exceeded(self.basic_user))

        record_message(self.basic_user)
        self.assertTrue(quota_exceeded(self.basic_user))

    def test_unlimited_role_never_trips_regardless_of_message_count(self):
        for _ in range(50):
            record_message(self.collab_user)
        self.assertFalse(quota_exceeded(self.collab_user))

    def test_messages_outside_the_rolling_window_are_not_counted(self):
        old = AgentChatMessageLog.objects.create(user=self.basic_user)
        old.created_at = timezone.now() - timedelta(days=2)
        old.save(update_fields=["created_at"])

        self.assertEqual(messages_used(self.basic_user), 0)


class AgentChatQuotaViewTests(TestCase):
    """Integration coverage for the enforcement point in
    AgentChatView.post -- mocks the LLM provider/agent (no real API calls),
    exercising only the quota gate and the record-on-success wiring."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="quota-view-user", password="x", role=TPUser.Role.BASIC
        )
        _grant_chat_permission(self.user)
        self.client.force_login(self.user)
        self.url = reverse("tpwebapp:agent_chat")

    @staticmethod
    def _mock_agent_instance(reply="ok"):
        instance = MagicMock()
        instance.run.return_value = reply
        instance.last_usage = MagicMock(input_tokens=1, output_tokens=1)
        instance.last_messages = []
        instance.last_turns = 1
        instance.last_tool_calls = []
        return instance

    def _post_message(self):
        return self.client.post(
            self.url,
            data=json.dumps({"message": "hola", "page_path": "/"}),
            content_type="application/json",
        )

    @patch("tpweb.views.AgentChatView.llm_agent_enabled", return_value=True)
    @patch("tpweb.views.AgentChatView.get_provider")
    @patch("tpweb.views.AgentChatView.Agent")
    def test_message_under_quota_succeeds_and_is_logged(
        self, agent_cls, get_provider, _llm_enabled
    ):
        get_provider.return_value = MagicMock(model="test-model")
        agent_cls.return_value = self._mock_agent_instance()

        response = self._post_message()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AgentChatMessageLog.objects.filter(user=self.user).count(), 1)

    @patch("tpweb.views.AgentChatView.llm_agent_enabled", return_value=True)
    @patch("tpweb.views.AgentChatView.get_provider")
    @patch("tpweb.views.AgentChatView.Agent")
    def test_message_at_quota_is_blocked_before_any_llm_call(
        self, agent_cls, get_provider, _llm_enabled
    ):
        quota = quota_for(self.user)
        for _ in range(quota):
            record_message(self.user)
        get_provider.return_value = MagicMock(model="test-model")
        agent_cls.return_value = self._mock_agent_instance()

        response = self._post_message()

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.json()["quota_exceeded"])
        agent_cls.assert_not_called()
        self.assertEqual(AgentChatMessageLog.objects.filter(user=self.user).count(), quota)

    @patch("tpweb.views.AgentChatView.llm_agent_enabled", return_value=True)
    @patch("tpweb.views.AgentChatView.get_provider")
    @patch("tpweb.views.AgentChatView.Agent")
    def test_gates_collaborator_role_is_never_blocked(self, agent_cls, get_provider, _llm_enabled):
        self.user.role = TPUser.Role.GATES_COLLABORATOR
        self.user.save(update_fields=["role"])
        for _ in range(50):
            record_message(self.user)
        get_provider.return_value = MagicMock(model="test-model")
        agent_cls.return_value = self._mock_agent_instance()

        response = self._post_message()

        self.assertEqual(response.status_code, 200)

    def test_anonymous_post_gets_401_json_not_a_bare_redirect_or_403(self):
        # Bypasses LoginRequiredMiddleware by hitting the view logic
        # directly -- see JsonPermissionRequiredMixin's own docstring for
        # why a real request never reaches this branch today (agent_chat
        # isn't in PUBLIC_URL_NAMES, so the middleware redirects first).
        # This still guards the mixin's own behavior in isolation.
        request = RequestFactory().post(
            self.url, data=json.dumps({"message": "hola"}), content_type="application/json"
        )
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        request.user = AnonymousUser()

        response = AgentChatView.as_view()(request)

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"], "login_required")
        self.assertIn("login_url", payload)

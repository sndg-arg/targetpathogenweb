from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tpweb.models.RequestLog import RequestLog


class RequestLogMiddlewareTests(TestCase):
    def test_authenticated_request_is_logged_with_user_and_ip(self):
        user = get_user_model().objects.create_user(username="req-log-user", password="test-pass")
        self.client.force_login(user)

        self.client.get(reverse("tpwebapp:about_us"), REMOTE_ADDR="203.0.113.5")

        row = RequestLog.objects.latest("created_at")
        self.assertEqual(row.user, user)
        self.assertEqual(row.ip, "203.0.113.5")
        self.assertEqual(row.method, "GET")
        self.assertEqual(row.path, reverse("tpwebapp:about_us"))
        self.assertEqual(row.status_code, 200)

    def test_anonymous_redirect_is_still_logged_without_a_user(self):
        self.client.get(reverse("tpwebapp:genome_upload"), REMOTE_ADDR="203.0.113.9")

        row = RequestLog.objects.latest("created_at")
        self.assertIsNone(row.user)
        self.assertEqual(row.ip, "203.0.113.9")
        self.assertEqual(row.status_code, 302)

    def test_health_check_is_not_logged(self):
        before = RequestLog.objects.count()

        self.client.get("/health/live")

        self.assertEqual(RequestLog.objects.count(), before)

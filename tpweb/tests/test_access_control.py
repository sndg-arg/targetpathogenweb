from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from tpweb.models.BlockedIP import BlockedIP
from tpweb.services.ip_blocking import block_ip


class BlockedIPMiddlewareTests(TestCase):
    """BlockedIPMiddleware sits ahead of LoginRequiredMiddleware in
    settings.MIDDLEWARE, so a blocked IP should never even reach the
    login-wall redirect, let alone an exempt path like robots.txt."""

    def setUp(self):
        cache.clear()

    def test_blocked_ip_gets_403_instead_of_the_login_redirect(self):
        block_ip("203.0.113.50")

        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"), REMOTE_ADDR="203.0.113.50"
        )

        self.assertEqual(response.status_code, 403)

    def test_unblocked_anonymous_request_still_gets_redirected_to_login(self):
        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"), REMOTE_ADDR="203.0.113.55"
        )

        self.assertEqual(response.status_code, 302)

    def test_blocked_ip_gets_403_even_on_exempt_paths(self):
        block_ip("203.0.113.51")

        response = self.client.get(reverse("tpwebapp:robots_txt"), REMOTE_ADDR="203.0.113.51")

        self.assertEqual(response.status_code, 403)

    def test_unblocked_ip_reaches_exempt_paths_normally(self):
        block_ip("203.0.113.52")

        response = self.client.get(reverse("tpwebapp:robots_txt"), REMOTE_ADDR="203.0.113.53")

        self.assertEqual(response.status_code, 200)

    def test_x_forwarded_for_first_hop_is_what_gets_checked(self):
        # Traefik sets X-Forwarded-For; REMOTE_ADDR alone would just be the
        # proxy's own IP. A comma-separated chain means the first hop is the
        # original client (see _first_forwarded_ip in observability.py).
        block_ip("203.0.113.54")

        response = self.client.get(
            reverse("tpwebapp:robots_txt"),
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.54, 10.0.0.1",
        )

        self.assertEqual(response.status_code, 403)


class AutoBlockBotTests(TestCase):
    """BlockedIPMiddleware also blocks on first sight -- no staff action
    needed for a User-Agent classified AI crawler / Generic bot."""

    def setUp(self):
        cache.clear()

    def test_ai_crawler_gets_blocked_on_first_non_exempt_request(self):
        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.90",
            HTTP_USER_AGENT="Mozilla/5.0 AppleWebKit/537.36 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
        )

        self.assertEqual(response.status_code, 403)
        blocked = BlockedIP.objects.get(ip="203.0.113.90")
        self.assertEqual(blocked.reason, "auto: AI crawler")
        self.assertIsNone(blocked.blocked_by)

    def test_generic_bot_gets_blocked_on_first_non_exempt_request(self):
        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.91",
            HTTP_USER_AGENT="some-generic-crawler/1.0",
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(BlockedIP.objects.filter(ip="203.0.113.91").exists())

    def test_second_request_from_the_same_ip_hits_the_now_cached_block(self):
        self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.96",
            HTTP_USER_AGENT="ClaudeBot/1.0",
        )

        response = self.client.get(
            reverse("tpwebapp:robots_txt"),
            REMOTE_ADDR="203.0.113.96",
            HTTP_USER_AGENT="Mozilla/5.0 (a completely different, human-looking UA now)",
        )

        self.assertEqual(response.status_code, 403)

    def test_search_crawler_is_not_auto_blocked(self):
        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.92",
            HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedIP.objects.filter(ip="203.0.113.92").exists())

    def test_http_client_is_not_auto_blocked(self):
        response = self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.93",
            HTTP_USER_AGENT="python-requests/2.31",
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedIP.objects.filter(ip="203.0.113.93").exists())

    def test_bot_requesting_only_robots_txt_is_left_alone(self):
        # The whole point of exempting robots.txt is letting a crawler read
        # "stay out" and back off on its own -- punishing it for reading it
        # would defeat that.
        response = self.client.get(
            reverse("tpwebapp:robots_txt"),
            REMOTE_ADDR="203.0.113.94",
            HTTP_USER_AGENT="ClaudeBot/1.0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(BlockedIP.objects.filter(ip="203.0.113.94").exists())

    def test_authenticated_request_is_never_auto_blocked(self):
        user = get_user_model().objects.create_user(username="auto-block-authed", password="x")
        self.client.force_login(user)

        self.client.get(
            reverse("tpwebapp:activity_dashboard"),
            REMOTE_ADDR="203.0.113.95",
            HTTP_USER_AGENT="ClaudeBot/1.0",
        )

        self.assertFalse(BlockedIP.objects.filter(ip="203.0.113.95").exists())

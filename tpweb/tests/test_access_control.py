from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

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

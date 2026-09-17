from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from bioseq.models.Biodatabase import Biodatabase
from tpweb.models.BlockedIP import BlockedIP
from tpweb.models.FilterPreset import FilterPreset
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


class VisitorBrowsingTests(TestCase):
    """LoginRequiredMiddleware's PUBLIC_URL_NAMES allow-list -- anonymous
    "Visitor" browsing works for the listed routes, and everything else
    (including routes that share a URL prefix with a public one, like
    genome/<g> vs genome/<g>/proteins/blast) still redirects to login."""

    def setUp(self):
        Biodatabase.objects.create(name="VISITORTEST", description="Genome workspace")
        Biodatabase.objects.create(name="VISITORTEST_prots")

    def test_anonymous_can_browse_public_pages(self):
        for name, kwargs in [
            ("index", {}),
            ("about_us", {}),
            ("data_sources", {}),
            ("genomes_list", {}),
            ("assembly", {"genome": "VISITORTEST"}),
            ("protein_list", {"genome": "VISITORTEST"}),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"tpwebapp:{name}", kwargs=kwargs))
                self.assertEqual(response.status_code, 200)

    def test_anonymous_is_still_redirected_from_gated_routes_under_the_same_genome_prefix(self):
        # The exact regression this test guards against: genome/<g> being
        # public must not accidentally make genome/<g>/proteins/blast,
        # genome/<g>/formula, or genome/<g>/custom-evidence public too via
        # loose prefix matching.
        for name, kwargs in [
            ("protein_blast", {"genome": "VISITORTEST"}),
            ("formula_form", {"genome": "VISITORTEST"}),
            ("customparam", {"genome": "VISITORTEST"}),
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"tpwebapp:{name}", kwargs=kwargs))
                self.assertEqual(response.status_code, 302)

    def test_anonymous_is_still_redirected_from_upload_activity_users_profile_and_chat(self):
        for name in ["genome_upload", "activity_dashboard", "user_management", "profile"]:
            with self.subTest(name=name):
                response = self.client.get(reverse(f"tpwebapp:{name}"))
                self.assertEqual(response.status_code, 302)

        response = self.client.post(reverse("tpwebapp:agent_chat"), content_type="application/json")
        self.assertEqual(response.status_code, 302)


class ProteinListPresetGuardTests(TestCase):
    """protein_list is public (VisitorBrowsingTests), but the three actions
    that write to the shared "public" workspace's FilterPreset rows must
    still require a real login -- see ProteinListView.post's guard, added
    once this view stopped being protected by the blanket login wall."""

    def setUp(self):
        Biodatabase.objects.create(name="VISITORTEST", description="Genome workspace")
        Biodatabase.objects.create(name="VISITORTEST_prots")
        self.url = reverse("tpwebapp:protein_list", kwargs={"genome": "VISITORTEST"})

    def test_anonymous_preset_actions_are_rejected(self):
        for action, extra in [
            ("save_filter_preset", {"preset_name": "mine"}),
            ("apply_filter_preset", {"preset_id": "1"}),
            ("delete_filter_preset", {"preset_id": "1"}),
        ]:
            with self.subTest(action=action):
                response = self.client.post(self.url, {"action": action, **extra})
                self.assertEqual(response.status_code, 302)
        self.assertFalse(FilterPreset.objects.exists())

    def test_anonymous_session_only_actions_still_work(self):
        response = self.client.post(self.url, {"action": "add_filter", "filter_option_id": "x"})
        self.assertEqual(response.status_code, 302)  # redirects back to the list, not to login
        self.assertNotIn(reverse("account_login"), response.url)

        response = self.client.post(self.url, {"action": "update_columns"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(reverse("account_login"), response.url)

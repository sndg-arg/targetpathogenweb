from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tpweb.models.RequestLog import RequestLog
from tpweb.services.activity_dashboard import build_activity_dashboard_data
from tpweb.services.workspace import get_public_workspace_user


class BuildActivityDashboardDataTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="alice", password="x")
        self.bob = get_user_model().objects.create_user(username="bob", password="x")

    def test_kpis_count_unique_users_and_ips_in_window(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.bob, ip="10.0.0.2", method="GET", path="/", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="10.0.0.3", method="GET", path="/genomes/upload", status_code=302
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["kpis"]["unique_users"], 2)
        self.assertEqual(data["kpis"]["unique_ips"], 3)
        self.assertEqual(data["kpis"]["requests_today"], 4)
        self.assertEqual(data["kpis"]["errors"], 0)

    def test_status_breakdown_buckets_by_first_digit(self):
        for code in (200, 200, 302, 404, 500):
            RequestLog.objects.create(
                user=self.alice, ip="10.0.0.1", method="GET", path="/x", status_code=code
            )

        data = build_activity_dashboard_data()
        counts = {row["bucket"]: row["count"] for row in data["status_breakdown"]}

        self.assertEqual(counts, {"2xx": 2, "3xx": 1, "4xx": 1, "5xx": 1})
        self.assertEqual(data["kpis"]["errors"], 2)

    def test_top_pages_normalizes_numeric_id_segments(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/protein/123", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/protein/456", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )

        data = build_activity_dashboard_data()
        top = {row["path"]: row["count"] for row in data["top_pages"]}

        self.assertEqual(top["/protein/<id>"], 2)
        self.assertEqual(top["/genomes"], 1)

    def test_top_pages_excludes_anonymous_scanning_traffic(self):
        # Everything sits behind LoginRequiredMiddleware -- an anonymous hit
        # never actually saw the page, it just bounced off the redirect. A
        # crawler hammering /protein/<id> shouldn't outweigh what the two
        # real accounts actually looked at.
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        for i in range(5):
            RequestLog.objects.create(
                user=None, ip="203.0.113.1", method="GET", path=f"/protein/{i}", status_code=302
            )

        data = build_activity_dashboard_data()
        top = {row["path"]: row["count"] for row in data["top_pages"]}

        self.assertEqual(top, {"/genomes": 1})

    def test_top_pages_excludes_non_page_endpoints(self):
        # /agent-chat (assistant messages) and /structure_raw/<id> (the 3D
        # viewer's raw file fetch) are hit as a side effect of using a real
        # page, not a page someone navigated to -- on a real deployment they
        # outranked every genuine page.
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="POST", path="/agent-chat", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/structure_raw/42", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice,
            ip="10.0.0.1",
            method="GET",
            path="/genome/TEST/proteins/suggestions",
            status_code=200,
        )

        data = build_activity_dashboard_data()
        top = {row["path"]: row["count"] for row in data["top_pages"]}

        self.assertEqual(top, {"/genomes": 1})

    def test_kpis_report_how_many_unique_ips_were_authenticated(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.1", method="GET", path="/genomes", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.2", method="GET", path="/genomes", status_code=302
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["kpis"]["unique_ips"], 3)
        self.assertEqual(data["kpis"]["unique_ips_authenticated"], 1)

    def test_blocked_requests_kpi_excludes_exempt_paths(self):
        # 2 genuinely blocked (redirected off a real page) + 1 anonymous hit
        # on the exempt login page (never redirected) -- only the first two
        # should count toward "blocked".
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.1", method="GET", path="/genomes", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.2", method="GET", path="/", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.3", method="GET", path="/accounts/login/", status_code=200
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["kpis"]["blocked_requests"], 2)
        # 2 blocked out of 4 total logged requests = 50%.
        self.assertEqual(data["kpis"]["blocked_requests_pct"], 50)

    def test_timeseries_splits_authenticated_from_anonymous_traffic(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.1", method="GET", path="/genomes", status_code=302
        )

        data = build_activity_dashboard_data()
        today_point = data["timeseries"][-1]

        self.assertEqual(today_point["authenticated"], 2)
        self.assertEqual(today_point["anonymous"], 1)

    def test_logging_started_at_reflects_the_earliest_request_log_row(self):
        older = RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/", status_code=200
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["logging_started_at"], older.created_at.isoformat())

    def test_accounts_lists_active_users_with_last_login(self):
        data = build_activity_dashboard_data()
        usernames = [a["username"] for a in data["accounts"]]

        self.assertIn("alice", usernames)
        self.assertIn("bob", usernames)

    def test_accounts_excludes_the_internal_public_workspace_user(self):
        get_public_workspace_user()

        data = build_activity_dashboard_data()
        usernames = [a["username"] for a in data["accounts"]]

        self.assertNotIn("public", usernames)

    def test_accounts_reports_is_staff_separately_from_is_superuser(self):
        # alice/bob (setUp) are plain users -- neither staff nor superuser.
        # A regular collaborator must not be badged "staff" in the UI, which
        # is what happens if this field is missing (JS treats "not
        # superuser" as "staff").
        get_user_model().objects.create_user(username="carol", password="x", is_staff=True)
        get_user_model().objects.create_user(
            username="dave", password="x", is_staff=True, is_superuser=True
        )

        data = build_activity_dashboard_data()
        by_username = {a["username"]: a for a in data["accounts"]}

        self.assertEqual(by_username["alice"]["is_staff"], False)
        self.assertEqual(by_username["alice"]["is_superuser"], False)
        self.assertEqual(by_username["carol"]["is_staff"], True)
        self.assertEqual(by_username["carol"]["is_superuser"], False)
        self.assertEqual(by_username["dave"]["is_staff"], True)
        self.assertEqual(by_username["dave"]["is_superuser"], True)

    def test_accounts_reports_the_real_name_falling_back_to_username(self):
        get_user_model().objects.create_user(
            username="named-user", password="x", name="Sol Varela Gamarnik"
        )

        data = build_activity_dashboard_data()
        by_username = {a["username"]: a for a in data["accounts"]}

        self.assertEqual(by_username["named-user"]["name"], "Sol Varela Gamarnik")
        # alice (setUp) never had a name set.
        self.assertEqual(by_username["alice"]["name"], "alice")


class LocationBreakdownTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="alice", password="x")

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_locations_include_geolocation_and_which_users_used_each_ip(self, mock_geolocate):
        mock_geolocate.return_value = {
            "country": "Brazil",
            "country_code": "BR",
            "city": "Sao Paulo",
            "region": "Sao Paulo",
        }
        RequestLog.objects.create(
            user=self.alice, ip="200.1.2.3", method="GET", path="/genomes", status_code=200
        )
        RequestLog.objects.create(
            user=self.alice, ip="200.1.2.3", method="GET", path="/", status_code=200
        )

        data = build_activity_dashboard_data()
        row = data["locations"][0]

        self.assertEqual(row["ip"], "200.1.2.3")
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["country"], "Brazil")
        self.assertEqual(row["country_code"], "BR")
        self.assertEqual(row["region"], "Sao Paulo")
        self.assertEqual(row["users"], ["alice"])

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_anonymous_requests_go_to_blocked_attempts_not_locations(self, mock_geolocate):
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None, ip="203.0.113.9", method="GET", path="/", status_code=302
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["locations"], [])
        row = data["blocked_attempts"][0]
        self.assertEqual(row["ip"], "203.0.113.9")
        self.assertIsNone(row["country"])
        self.assertNotIn("users", row)

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_exempt_paths_dont_count_as_blocked_attempts(self, mock_geolocate):
        # LoginRequiredMiddleware never redirects EXEMPT_PATH_PREFIXES (mainly
        # /accounts/) -- an anonymous visit to the login page itself is
        # completely normal traffic, not someone hitting the login wall.
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None, ip="203.0.113.9", method="GET", path="/accounts/login/", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.10", method="GET", path="/genomes", status_code=302
        )

        data = build_activity_dashboard_data()
        blocked_ips = {row["ip"] for row in data["blocked_attempts"]}

        self.assertNotIn("203.0.113.9", blocked_ips)
        self.assertIn("203.0.113.10", blocked_ips)


class IpBreakdownDetailTests(TestCase):
    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_blocked_attempts_report_top_user_agent_and_distinct_path_count(self, mock_geolocate):
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.30",
            method="GET",
            path="/wp-login.php",
            status_code=302,
            user_agent="python-requests/2.31",
        )
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.30",
            method="GET",
            path="/.env",
            status_code=302,
            user_agent="python-requests/2.31",
        )
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.30",
            method="GET",
            path="/.env",
            status_code=302,
            user_agent="python-requests/2.31",
        )

        data = build_activity_dashboard_data()
        row = data["blocked_attempts"][0]

        self.assertEqual(row["ip"], "203.0.113.30")
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["distinct_paths"], 2)
        self.assertEqual(row["user_agent"], "python-requests/2.31")


class LoginAttemptsTests(TestCase):
    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_failed_login_post_is_a_login_attempt_not_a_blocked_scan(self, mock_geolocate):
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.20",
            method="POST",
            path="/accounts/login/",
            status_code=200,
            user_agent="Mozilla/5.0",
        )

        data = build_activity_dashboard_data()

        login_ips = {row["ip"] for row in data["login_attempts"]}
        blocked_ips = {row["ip"] for row in data["blocked_attempts"]}
        self.assertIn("203.0.113.20", login_ips)
        self.assertNotIn("203.0.113.20", blocked_ips)

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_get_to_login_page_is_not_a_login_attempt(self, mock_geolocate):
        # Just opening the login form isn't "trying to log in" -- only a
        # POST submits credentials.
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None, ip="203.0.113.21", method="GET", path="/accounts/login/", status_code=200
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["login_attempts"], [])

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_successful_login_post_is_not_counted_as_a_failed_attempt(self, mock_geolocate):
        # login() sets request.user on the same request before the
        # middleware logs it, so a successful POST has user set already.
        mock_geolocate.return_value = None
        alice = get_user_model().objects.create_user(username="alice", password="x")
        RequestLog.objects.create(
            user=alice, ip="203.0.113.22", method="POST", path="/accounts/login/", status_code=302
        )

        data = build_activity_dashboard_data()

        self.assertEqual(data["login_attempts"], [])


class BotTrafficSummaryTests(TestCase):
    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_aggregates_every_blocked_request_by_classified_bot_type(self, mock_geolocate):
        mock_geolocate.return_value = None
        # 3 distinct ClaudeBot IPs -- individually they'd fill 3 of the
        # top-10 _blocked_attempts_breakdown slots, but the summary should
        # still report them as one "AI crawler" bucket with ip_count=3.
        for i in range(3):
            RequestLog.objects.create(
                user=None,
                ip=f"203.0.113.{i}",
                method="GET",
                path="/genomes",
                status_code=302,
                user_agent="Mozilla/5.0 AppleWebKit/537.36 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
            )
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.50",
            method="GET",
            path="/genomes",
            status_code=302,
            user_agent="curl/8.4.0",
        )
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.51",
            method="GET",
            path="/genomes",
            status_code=302,
            user_agent="SomeWeirdUnrecognizedClient/1.0",
        )

        data = build_activity_dashboard_data()
        by_label = {row["label"]: row for row in data["bot_traffic_summary"]}

        self.assertEqual(
            by_label["AI crawler"], {"label": "AI crawler", "ip_count": 3, "requests": 3}
        )
        # curl and the unrecognized client both fail every pattern -- neither
        # is a guessed match, so both land in "Unclassified" together.
        self.assertEqual(
            by_label["Unclassified"], {"label": "Unclassified", "ip_count": 2, "requests": 2}
        )

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_worker_pattern_is_classified_as_generic_bot(self, mock_geolocate):
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None,
            ip="203.0.113.60",
            method="GET",
            path="/genomes",
            status_code=302,
            user_agent="crusader-worker/1.0",
        )

        data = build_activity_dashboard_data()
        by_label = {row["label"]: row for row in data["bot_traffic_summary"]}

        self.assertIn("Generic bot", by_label)
        self.assertEqual(by_label["Generic bot"]["ip_count"], 1)


class TopErrorPathsTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="alice", password="x")

    def test_favicon_and_robots_txt_404s_are_excluded_as_noise(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/favicon.ico", status_code=404
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/robots.txt", status_code=404
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/accounts/login", status_code=403
        )

        data = build_activity_dashboard_data()
        paths = {row["path"] for row in data["top_error_paths"]}

        self.assertNotIn("/favicon.ico", paths)
        self.assertNotIn("/robots.txt", paths)
        self.assertIn("/accounts/login", paths)

    def test_groups_by_normalized_path_and_breaks_down_status_codes(self):
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/protein/123", status_code=404
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/protein/456", status_code=404
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/protein/456", status_code=500
        )
        RequestLog.objects.create(
            user=self.alice, ip="10.0.0.1", method="GET", path="/genomes", status_code=200
        )

        data = build_activity_dashboard_data()
        by_path = {row["path"]: row for row in data["top_error_paths"]}

        self.assertEqual(by_path["/protein/<id>"]["count"], 3)
        codes = {c["code"]: c["count"] for c in by_path["/protein/<id>"]["codes"]}
        self.assertEqual(codes, {404: 2, 500: 1})
        self.assertNotIn("/genomes", by_path)


class TopScannedPathsTests(TestCase):
    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_groups_blocked_traffic_by_normalized_path_with_ip_and_request_counts(
        self, mock_geolocate
    ):
        mock_geolocate.return_value = None
        # 2 distinct IPs both probing /wp-login.php -- a path several
        # different actors hit is the more interesting scan target than one
        # actor hitting many paths, so ip_count is tracked separately from
        # the raw requests count.
        RequestLog.objects.create(
            user=None, ip="203.0.113.10", method="GET", path="/wp-login.php", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.11", method="GET", path="/wp-login.php", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.10", method="GET", path="/wp-login.php", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.20", method="GET", path="/protein/123", status_code=302
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.21", method="GET", path="/protein/456", status_code=302
        )

        data = build_activity_dashboard_data()
        by_path = {row["path"]: row for row in data["top_scanned_paths"]}

        self.assertEqual(
            by_path["/wp-login.php"], {"path": "/wp-login.php", "requests": 3, "ip_count": 2}
        )
        # Numeric-id segments collapse the same as top_error_paths/top_pages.
        self.assertEqual(
            by_path["/protein/<id>"], {"path": "/protein/<id>", "requests": 2, "ip_count": 2}
        )

    @patch("tpweb.services.activity_dashboard.geolocate_ip")
    def test_authenticated_and_exempt_traffic_is_excluded(self, mock_geolocate):
        mock_geolocate.return_value = None
        alice = get_user_model().objects.create_user(username="alice-scan", password="x")
        RequestLog.objects.create(
            user=alice, ip="10.0.0.1", method="GET", path="/some/page", status_code=200
        )
        RequestLog.objects.create(
            user=None, ip="203.0.113.30", method="GET", path="/accounts/login", status_code=200
        )

        data = build_activity_dashboard_data()
        paths = {row["path"] for row in data["top_scanned_paths"]}

        self.assertNotIn("/some/page", paths)
        self.assertNotIn("/accounts/login", paths)


class ActivityDashboardViewTests(TestCase):
    def test_superuser_can_view_dashboard(self):
        owner = get_user_model().objects.create_user(
            username="dash-owner", password="x", is_staff=True, is_superuser=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activity")
        self.assertContains(response, "Blocked by login wall")

    def test_staff_non_superuser_is_forbidden(self):
        # Approval grants is_staff, not is_superuser -- an approved
        # collaborator must not see visitor IP/security telemetry.
        staff_user = get_user_model().objects.create_user(
            username="dash-staff", password="x", is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_non_staff_user_is_forbidden(self):
        regular_user = get_user_model().objects.create_user(username="dash-regular", password="x")
        self.client.force_login(regular_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 302)

    def test_user_with_explicit_permission_can_view_dashboard(self):
        from django.contrib.auth.models import Permission

        granted_user = get_user_model().objects.create_user(
            username="dash-granted", password="x", is_staff=True
        )
        granted_user.user_permissions.add(
            Permission.objects.get(content_type__app_label="tpweb", codename="can_view_activity")
        )
        self.client.force_login(granted_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 200)

    def test_defaults_to_a_7_day_window(self):
        owner = get_user_model().objects.create_user(
            username="dash-period-default", password="x", is_staff=True, is_superuser=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.context["window_days"], 7)
        self.assertEqual(response.context["activity_dashboard_data"]["kpis"]["window_days"], 7)
        self.assertContains(response, "Requests, last 7 days")

    def test_days_query_param_switches_the_window(self):
        owner = get_user_model().objects.create_user(
            username="dash-period-30", password="x", is_staff=True, is_superuser=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"), {"days": "30"})

        self.assertEqual(response.context["window_days"], 30)
        self.assertContains(response, "Requests, last 30 days")

    def test_invalid_days_query_param_falls_back_to_the_default(self):
        owner = get_user_model().objects.create_user(
            username="dash-period-invalid", password="x", is_staff=True, is_superuser=True
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"), {"days": "9999"})

        self.assertEqual(response.context["window_days"], 7)

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


class TopErrorPathsTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user(username="alice", password="x")

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


class ActivityDashboardViewTests(TestCase):
    def test_staff_user_can_view_dashboard(self):
        staff_user = get_user_model().objects.create_user(
            username="dash-staff", password="x", is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activity")
        self.assertContains(response, "Blocked by login wall")

    def test_non_staff_user_is_forbidden(self):
        regular_user = get_user_model().objects.create_user(username="dash-regular", password="x")
        self.client.force_login(regular_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 302)

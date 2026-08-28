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
    def test_locations_handle_an_unresolved_ip_gracefully(self, mock_geolocate):
        mock_geolocate.return_value = None
        RequestLog.objects.create(
            user=None, ip="203.0.113.9", method="GET", path="/", status_code=200
        )

        data = build_activity_dashboard_data()
        row = data["locations"][0]

        self.assertIsNone(row["country"])
        self.assertEqual(row["users"], [])


class ActivityDashboardViewTests(TestCase):
    def test_staff_user_can_view_dashboard(self):
        staff_user = get_user_model().objects.create_user(
            username="dash-staff", password="x", is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activity")

    def test_non_staff_user_is_forbidden(self):
        regular_user = get_user_model().objects.create_user(username="dash-regular", password="x")
        self.client.force_login(regular_user)

        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("tpwebapp:activity_dashboard"))

        self.assertEqual(response.status_code, 302)

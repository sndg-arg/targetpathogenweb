from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from tpweb.services.ip_geolocation import geolocate_ip


class GeolocateIpTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("tpweb.services.ip_geolocation.requests.get")
    def test_private_ips_are_never_looked_up(self, mock_get):
        for ip in ("10.0.0.5", "192.168.1.1", "127.0.0.1", "172.16.4.4"):
            self.assertIsNone(geolocate_ip(ip))
        mock_get.assert_not_called()

    @patch("tpweb.services.ip_geolocation.requests.get")
    def test_successful_lookup_returns_parsed_location(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "status": "success",
                "country": "Brazil",
                "countryCode": "BR",
                "city": "Sao Paulo",
                "regionName": "Sao Paulo",
            }
        )

        location = geolocate_ip("200.1.2.3")

        self.assertEqual(location["country"], "Brazil")
        self.assertEqual(location["country_code"], "BR")
        self.assertEqual(location["city"], "Sao Paulo")

    @patch("tpweb.services.ip_geolocation.requests.get")
    def test_second_lookup_for_the_same_ip_hits_the_cache_not_the_api(self, mock_get):
        mock_get.return_value = Mock(
            json=lambda: {
                "status": "success",
                "country": "Argentina",
                "countryCode": "AR",
                "city": "Buenos Aires",
                "regionName": "Buenos Aires",
            }
        )

        first = geolocate_ip("181.1.1.1")
        second = geolocate_ip("181.1.1.1")

        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @patch("tpweb.services.ip_geolocation.requests.get")
    def test_lookup_failure_returns_none_without_raising(self, mock_get):
        mock_get.side_effect = Exception("network is down")

        self.assertIsNone(geolocate_ip("8.8.8.8"))

    @patch("tpweb.services.ip_geolocation.requests.get")
    def test_api_reporting_failed_status_returns_none(self, mock_get):
        mock_get.return_value = Mock(json=lambda: {"status": "fail", "message": "invalid query"})

        self.assertIsNone(geolocate_ip("0.0.0.0"))

    def test_malformed_ip_returns_none(self):
        self.assertIsNone(geolocate_ip("not-an-ip"))
        self.assertIsNone(geolocate_ip(""))
        self.assertIsNone(geolocate_ip(None))

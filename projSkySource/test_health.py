from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_returns_ok_without_login(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_returns_503_when_database_is_down(self):
        with patch("projSkySource.health.connection") as mock_conn:
            mock_conn.cursor.side_effect = Exception("db down")
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)

    def test_post_is_not_allowed(self):
        response = self.client.post(reverse("health"))
        self.assertEqual(response.status_code, 405)

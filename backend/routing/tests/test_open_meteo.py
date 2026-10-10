from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import SimpleTestCase

from routing.providers.open_meteo import OpenMeteoProvider


class OpenMeteoProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.now = datetime(2026, 10, 10, tzinfo=UTC)
        start = int(self.now.timestamp())
        self.forecast = {
            "hourly": {
                "time": [start, start + 3600],
                "wind_speed_10m": [5, 7],
                "rain": [0, 0],
                "snowfall": [0, 0],
            }
        }

    def test_batches_up_to_100_locations(self):
        locations = [
            (index / 1000, 0, self.now + timedelta(minutes=30))
            for index in range(101)
        ]

        def response_for(url, *, timeout_seconds):
            count = len(parse_qs(urlsplit(url).query)["latitude"][0].split(","))
            return [self.forecast] * count

        with patch("routing.providers.open_meteo.get_json", side_effect=response_for) as request:
            readings = OpenMeteoProvider().fetch_at(locations, now=self.now)

        batch_sizes = [
            len(parse_qs(urlsplit(call.args[0]).query)["latitude"][0].split(","))
            for call in request.call_args_list
        ]
        self.assertEqual(len(readings), 101)
        self.assertEqual(sorted(batch_sizes), [1, 100])

    def test_caches_identical_provider_requests(self):
        locations = [(0, 0, self.now + timedelta(minutes=30))]

        with patch("routing.providers.open_meteo.get_json", return_value=self.forecast) as request:
            first = OpenMeteoProvider().fetch_at(locations, now=self.now)
            second = OpenMeteoProvider().fetch_at(locations, now=self.now)

        self.assertEqual(first, second)
        request.assert_called_once()

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from routing.providers.http import ProviderError
from routing.providers.weather_api import WeatherApiProvider


@override_settings(WEATHERAPI_API_KEY="demo-key")
class WeatherApiProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.now = datetime(2026, 10, 10, tzinfo=UTC)
        start = int(self.now.timestamp())
        self.forecast = {
            "forecast": {
                "forecastday": [
                    {
                        "hour": [
                            {
                                "time_epoch": start + index * 3600,
                                "wind_mph": 5 + index * 2,
                                "precip_in": 0.1 * (index + 1),
                                "snow_cm": 0.254 * (index + 1),
                            }
                            for index in range(3)
                        ]
                    }
                ]
            }
        }

    def test_fetches_a_unique_coordinate_once_and_converts_snowfall(self):
        locations = [
            (10, 20, self.now + timedelta(minutes=30)),
            (10, 20, self.now + timedelta(minutes=90)),
        ]

        with patch("routing.providers.weather_api.get_json", return_value=self.forecast) as request:
            readings = WeatherApiProvider().fetch_at(locations, now=self.now)

        self.assertEqual(request.call_count, 1)
        self.assertEqual([reading.wind_mph for reading in readings], [6, 8])
        self.assertEqual([reading.rain_in_per_hour for reading in readings], [0.1, 0.2])
        self.assertEqual([reading.snow_in_per_hour for reading in readings], [0.1, 0.2])

    def test_caches_identical_forecast_requests(self):
        locations = [(10, 20, self.now + timedelta(minutes=30))]

        with patch("routing.providers.weather_api.get_json", return_value=self.forecast) as request:
            first = WeatherApiProvider().fetch_at(locations, now=self.now)
            second = WeatherApiProvider().fetch_at(locations, now=self.now)

        self.assertEqual(first, second)
        request.assert_called_once()

    @override_settings(WEATHERAPI_API_KEY="")
    def test_requires_backend_api_key(self):
        with self.assertRaisesMessage(ProviderError, "Set WEATHERAPI_API_KEY"):
            WeatherApiProvider().fetch_at(
                [(10, 20, self.now + timedelta(minutes=30))],
                now=self.now,
            )

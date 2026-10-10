from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from routing.domain.analysis import analyze_trip
from routing.domain.risk import WeatherReading
from routing.providers.mapbox import CandidateRoute, ResolvedLocation


class AnalyzeTripTests(SimpleTestCase):
    @patch('routing.domain.analysis.OpenMeteoProvider')
    @patch('routing.domain.analysis.MapboxProvider')
    def test_recommends_the_lower_risk_route_even_when_it_takes_longer(self, mapbox_class, weather_class):
        routing = mapbox_class.return_value
        routing.geocode.side_effect = (
            ResolvedLocation('Origin', 0, 0),
            ResolvedLocation('Destination', 1, 0),
        )
        routing.get_three_routes.return_value = (
            CandidateRoute('fast-severe', ((0, 0), (1, 0)), (100,), 100, 3600, 'fast'),
            CandidateRoute('slow-safe', ((0, 0), (1, 0)), (100,), 100, 7200, 'safe'),
            CandidateRoute('middle-high', ((0, 0), (1, 0)), (100,), 100, 5400, 'middle'),
        )
        weather_class.return_value.fetch_at.return_value = (
            [WeatherReading(45, 0, 0)] * 3
            + [WeatherReading(0, 0, 0)] * 3
            + [WeatherReading(35, 0, 0)] * 3
        )

        result = analyze_trip(
            origin_query='Origin',
            destination_query='Destination',
            departure_time=timezone.now() + timedelta(hours=1),
            load_weight_lb=0,
            checkpoint_interval_miles=50,
        )

        self.assertEqual(result['recommendation_id'], 'slow-safe')
        self.assertEqual([route['id'] for route in result['routes']], [
            'slow-safe', 'middle-high', 'fast-severe',
        ])
        self.assertEqual([route['rank'] for route in result['routes']], [1, 2, 3])
        self.assertEqual(result['routes'][0]['risk_summary']['average_risk'], 0)
        self.assertEqual(result['routes'][2]['risk_summary']['severe_miles'], 100)
        self.assertTrue(all('_sort_key' not in route for route in result['routes']))
        weather_class.return_value.fetch_at.assert_called_once()

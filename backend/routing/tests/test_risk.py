from django.test import SimpleTestCase

from routing.domain.risk import (
    CheckpointRisk,
    RiskLevel,
    RouteRiskSummary,
    WeatherReading,
    classify_checkpoint,
    rank_route_key,
    summarize_route_risk,
)


class CheckpointRiskTests(SimpleTestCase):
    def test_wind_thresholds(self):
        cases = (
            (24.99, RiskLevel.LOW),
            (25, RiskLevel.MODERATE),
            (34.99, RiskLevel.MODERATE),
            (35, RiskLevel.HIGH),
            (44.99, RiskLevel.HIGH),
            (45, RiskLevel.SEVERE),
            (54.99, RiskLevel.SEVERE),
            (55, RiskLevel.NO_TRAVEL),
        )
        for wind, expected in cases:
            with self.subTest(wind=wind):
                result = classify_checkpoint(WeatherReading(wind, 0, 0), 0)
                self.assertEqual(result.level, expected)

    def test_rain_thresholds(self):
        cases = (
            (0.099, RiskLevel.LOW),
            (0.10, RiskLevel.MODERATE),
            (0.249, RiskLevel.MODERATE),
            (0.25, RiskLevel.HIGH),
            (0.499, RiskLevel.HIGH),
            (0.50, RiskLevel.SEVERE),
            (1.00, RiskLevel.SEVERE),
            (1.001, RiskLevel.NO_TRAVEL),
        )
        for rain, expected in cases:
            with self.subTest(rain=rain):
                result = classify_checkpoint(WeatherReading(0, rain, 0), 0)
                self.assertEqual(result.level, expected)

    def test_snow_thresholds(self):
        cases = (
            (0.499, RiskLevel.LOW),
            (0.5, RiskLevel.MODERATE),
            (0.999, RiskLevel.MODERATE),
            (1.0, RiskLevel.HIGH),
            (1.999, RiskLevel.HIGH),
            (2.0, RiskLevel.SEVERE),
            (3.0, RiskLevel.SEVERE),
            (3.001, RiskLevel.NO_TRAVEL),
        )
        for snow, expected in cases:
            with self.subTest(snow=snow):
                result = classify_checkpoint(WeatherReading(0, 0, snow), 0)
                self.assertEqual(result.level, expected)

    def test_load_changes_wind_risk_only_above_documented_limits(self):
        at_30000 = classify_checkpoint(WeatherReading(45, 0, 0), 30_000)
        over_30000 = classify_checkpoint(WeatherReading(45, 0, 0), 30_001)
        at_40000 = classify_checkpoint(WeatherReading(35, 0, 0), 40_000)
        over_40000 = classify_checkpoint(WeatherReading(35, 0, 0), 40_001)

        self.assertEqual(at_30000.level, RiskLevel.SEVERE)
        self.assertIsNone(at_30000.load_adjustment)
        self.assertEqual(over_30000.level, RiskLevel.NO_TRAVEL)
        self.assertEqual(over_30000.load_adjustment, RiskLevel.NO_TRAVEL)
        self.assertEqual(at_40000.level, RiskLevel.HIGH)
        self.assertIsNone(at_40000.load_adjustment)
        self.assertEqual(over_40000.level, RiskLevel.SEVERE)
        self.assertEqual(over_40000.load_adjustment, RiskLevel.SEVERE)

    def test_worst_hazard_controls_checkpoint(self):
        result = classify_checkpoint(WeatherReading(0, 1.01, 0), 0)
        self.assertEqual(result.rain_level, RiskLevel.NO_TRAVEL)
        self.assertEqual(result.level, RiskLevel.NO_TRAVEL)

    def test_invalid_measurements_are_rejected(self):
        for reading, load in (
            (WeatherReading(-1, 0, 0), 0),
            (WeatherReading(0, float('nan'), 0), 0),
            (WeatherReading(0, 0, 0), -1),
        ):
            with self.subTest(reading=reading, load=load), self.assertRaises(ValueError):
                classify_checkpoint(reading, load)


class RouteRiskSummaryTests(SimpleTestCase):
    def test_risk_miles_are_weighted_by_route_segments(self):
        result = summarize_route_risk(100, (
            (0, RiskLevel.LOW),
            (50, RiskLevel.SEVERE),
            (100, RiskLevel.HIGH),
        ))
        self.assertEqual(result.severe_miles, 50)
        self.assertEqual(result.high_miles, 25)
        self.assertEqual(result.average_risk, 2)
        self.assertEqual(result.no_travel_miles, 0)
        self.assertTrue(result.eligible)

    def test_no_travel_miles_make_a_route_ineligible(self):
        result = summarize_route_risk(10, ((0, RiskLevel.LOW), (10, RiskLevel.NO_TRAVEL)))
        self.assertFalse(result.eligible)
        self.assertGreater(result.no_travel_miles, 0)

    def test_route_rank_uses_risk_priority_before_duration(self):
        fewer_severe = RouteRiskSummary(0, 20, 1.5, 0)
        less_high = RouteRiskSummary(5, 0, 1.0, 0)
        shorter_only = RouteRiskSummary(5, 20, 1.5, 0)
        no_travel = RouteRiskSummary(0, 0, 0, 1)

        self.assertLess(rank_route_key(fewer_severe, 20_000), rank_route_key(less_high, 1_000))
        self.assertLess(rank_route_key(less_high, 20_000), rank_route_key(shorter_only, 1_000))
        self.assertLess(rank_route_key(shorter_only, 1_000), rank_route_key(shorter_only, 2_000))
        self.assertLess(rank_route_key(shorter_only, 1), rank_route_key(no_travel, 1))

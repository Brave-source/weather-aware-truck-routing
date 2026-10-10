from django.test import SimpleTestCase

from routing.domain.checkpoints import place_checkpoints


class PlaceCheckpointsTests(SimpleTestCase):
    def test_places_interval_samples_and_endpoints_with_proportional_etas(self):
        points = place_checkpoints(
            ((0, 0), (1, 0)),
            interval_miles=40,
            duration_seconds=3600,
            segment_lengths_miles=(100,),
        )
        self.assertEqual([point.mile for point in points], [0, 40, 80, 100])
        self.assertEqual([point.elapsed_seconds for point in points], [0, 1440, 2880, 3600])
        self.assertAlmostEqual(points[1].longitude, 0.4)
        self.assertAlmostEqual(points[1].latitude, 0)
        self.assertEqual((points[-1].longitude, points[-1].latitude), (1, 0))

    def test_interval_longer_than_route_keeps_both_endpoints(self):
        points = place_checkpoints(
            ((0, 0), (1, 0)),
            interval_miles=200,
            duration_seconds=120,
            segment_lengths_miles=(100,),
        )
        self.assertEqual([point.mile for point in points], [0, 100])
        self.assertEqual([point.elapsed_seconds for point in points], [0, 120])

    def test_interpolation_uses_shorter_path_across_date_line(self):
        points = place_checkpoints(((179, 0), (-179, 0)), 70, 100, (120,))
        self.assertGreater(abs(points[1].longitude), 179.8)

    def test_rejects_invalid_route_geometry_and_spacing(self):
        invalid_inputs = (
            (((0, 0),), 10, 60, None),
            (((0, 91), (1, 0)), 10, 60, None),
            (((0, 0), (1, 0)), 0, 60, None),
            (((0, 0), (1, 0)), 10, -1, None),
            (((0, 0), (1, 0)), 10, 60, ()),
            (((0, 0), (0, 0)), 10, 60, None),
        )
        for geometry, interval, duration, lengths in invalid_inputs:
            with self.subTest(geometry=geometry, interval=interval), self.assertRaises(ValueError):
                place_checkpoints(geometry, interval, duration, lengths)

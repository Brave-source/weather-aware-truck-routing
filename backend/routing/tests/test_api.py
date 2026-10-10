from django.test import SimpleTestCase
from rest_framework.test import APIClient


class ApiSmokeTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint_reports_service_status(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_location_search_rejects_queries_shorter_than_three_characters(self):
        response = self.client.get('/api/location-suggestions/', {'q': 'ab'})
        self.assertEqual(response.status_code, 400)

    def test_route_analysis_rejects_missing_trip_fields(self):
        response = self.client.post('/api/route-analysis/', {}, format='json')
        self.assertEqual(response.status_code, 400)

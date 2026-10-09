from django.urls import path

from .views import analyze_corridor_forecast, analyze_route, health, location_suggestions

urlpatterns = [
    path("health/", health, name="health"),
    path("location-suggestions/", location_suggestions, name="location-suggestions"),
    path("route-analysis/", analyze_route, name="route-analysis"),
    path("corridor-forecast/", analyze_corridor_forecast, name="corridor-forecast"),
]

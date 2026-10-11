from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .domain.analysis import analyze_trip
from .domain.risk import classify_checkpoint
from .providers.http import ProviderError
from .providers.mapbox import MapboxProvider
from .providers.weather_api import ForecastWindowError, WeatherApiProvider
from .serializers import (
    CorridorForecastRequestSerializer,
    LocationSuggestionRequestSerializer,
    RouteAnalysisRequestSerializer,
)


@api_view(["GET"])
def health(_request):
    return Response({"status": "ok", "service": "weather-aware-routing-api"})


@api_view(["GET"])
def location_suggestions(request):
    serializer = LocationSuggestionRequestSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    try:
        suggestions = MapboxProvider().suggest_locations(serializer.validated_data["q"])
    except ProviderError as error:
        return Response({"message": str(error)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({"suggestions": suggestions})


@api_view(["POST"])
def analyze_route(request):
    serializer = RouteAnalysisRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        result = analyze_trip(
            origin_query=data["origin"],
            destination_query=data["destination"],
            departure_time=data["departure_time"],
            load_weight_lb=data["load_weight_lb"],
            checkpoint_interval_miles=data["checkpoint_interval_miles"],
        )
    except ValueError as error:
        return Response({"message": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    except ForecastWindowError as error:
        return Response({"message": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    except ProviderError as error:
        return Response({"message": str(error)}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(result)


@api_view(["POST"])
def analyze_corridor_forecast(request):
    serializer = CorridorForecastRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["departure_time"] < timezone.now():
        return Response(
            {"message": "The selected forecast time is in the past."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    forecast_time = data["departure_time"] + timedelta(hours=data["forecast_offset_hours"])
    checkpoints = data["checkpoints"]
    locations = [
        (point["longitude"], point["latitude"], forecast_time)
        for point in checkpoints
    ]
    try:
        readings = WeatherApiProvider().fetch_at(
            locations,
        )
    except ForecastWindowError as error:
        return Response({"message": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    except ProviderError as error:
        return Response({"message": str(error)}, status=status.HTTP_502_BAD_GATEWAY)

    routes = {}
    for checkpoint, reading in zip(checkpoints, readings):
        classified = classify_checkpoint(reading, data["load_weight_lb"])
        routes.setdefault(checkpoint["route_id"], []).append(
            {
                "mile": float(checkpoint["mile"]),
                "longitude": float(checkpoint["longitude"]),
                "latitude": float(checkpoint["latitude"]),
                "risk": classified.level.name.replace("_", " ").title(),
                "weather": {
                    "wind_mph": round(reading.wind_mph, 1),
                    "rain_in_per_hour": round(reading.rain_in_per_hour, 3),
                    "snow_in_per_hour": round(reading.snow_in_per_hour, 2),
                },
            }
        )
    return Response(
        {
            "forecast_time": forecast_time.isoformat(),
            "forecast_offset_hours": data["forecast_offset_hours"],
            "routes": routes,
            "weather_source": "WeatherAPI.com",
        }
    )

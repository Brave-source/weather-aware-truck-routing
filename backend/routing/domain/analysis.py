from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from ..providers.http import ProviderError
from ..providers.mapbox import MapboxProvider
from ..providers.weather_api import WeatherApiProvider
from .checkpoints import place_checkpoints
from .risk import RiskLevel, classify_checkpoint, rank_route_key, summarize_route_risk


def _risk_label(level: RiskLevel) -> str:
    return level.name.replace("_", " ").title()


def analyze_trip(
    *,
    origin_query: str,
    destination_query: str,
    departure_time: datetime,
    load_weight_lb: float,
    checkpoint_interval_miles: int,
) -> dict:
    if timezone.is_naive(departure_time):
        raise ValueError("departure_time must include a timezone")
    if departure_time < timezone.now():
        raise ValueError("departure_time must be in the future to use a live forecast")

    routing = MapboxProvider()
    origin = routing.geocode(origin_query)
    destination = routing.geocode(destination_query)
    candidates = routing.get_three_routes(origin, destination, departure_time.isoformat())

    route_checkpoints = []
    provider_locations = []
    for route in candidates:
        checkpoints = place_checkpoints(
            route.geometry,
            interval_miles=checkpoint_interval_miles,
            duration_seconds=route.duration_seconds,
            segment_lengths_miles=route.segment_lengths_miles,
        )
        route_checkpoints.append(checkpoints)
        # Sample weather at each checkpoint's estimated arrival time.
        provider_locations.extend(
            (
                checkpoint.longitude,
                checkpoint.latitude,
                departure_time + timedelta(seconds=checkpoint.elapsed_seconds),
            )
            for checkpoint in checkpoints
        )

    weather_readings = WeatherApiProvider().fetch_at(provider_locations)
    if len(weather_readings) != len(provider_locations):
        raise ProviderError("Weather data did not match all route checkpoints.")

    results = []
    reading_index = 0
    for route_index, (route, checkpoints) in enumerate(zip(candidates, route_checkpoints), start=1):
        checkpoint_results = []
        route_samples = []
        for checkpoint in checkpoints:
            reading = weather_readings[reading_index]
            reading_index += 1
            classified = classify_checkpoint(reading, load_weight_lb)
            route_samples.append((checkpoint.mile, classified.level))
            arrival_time = departure_time + timedelta(seconds=checkpoint.elapsed_seconds)
            checkpoint_results.append(
                {
                    "mile": round(checkpoint.mile, 2),
                    "longitude": checkpoint.longitude,
                    "latitude": checkpoint.latitude,
                    "arrival_time": arrival_time.isoformat(),
                    "elapsed_seconds": round(checkpoint.elapsed_seconds),
                    "risk": _risk_label(classified.level),
                    "weather": {
                        "wind_mph": round(reading.wind_mph, 1),
                        "rain_in_per_hour": round(reading.rain_in_per_hour, 3),
                        "snow_in_per_hour": round(reading.snow_in_per_hour, 2),
                    },
                    "hazards": {
                        "wind": _risk_label(classified.wind_level),
                        "rain": _risk_label(classified.rain_level),
                        "snow": _risk_label(classified.snow_level),
                        "load_adjustment": _risk_label(classified.load_adjustment)
                        if classified.load_adjustment is not None
                        else None,
                    },
                }
            )

        summary = summarize_route_risk(route.distance_miles, route_samples)
        results.append(
            {
                "id": route.route_id,
                "route_number": route_index,
                "strategy": route.strategy,
                "geometry": [list(point) for point in route.geometry],
                "distance_miles": round(route.distance_miles, 1),
                "duration_seconds": round(route.duration_seconds),
                "estimated_arrival": (
                    departure_time + timedelta(seconds=route.duration_seconds)
                ).isoformat(),
                "risk_summary": {
                    "severe_miles": round(summary.severe_miles, 1),
                    "high_miles": round(summary.high_miles, 1),
                    "average_risk": round(summary.average_risk, 2),
                    "no_travel_miles": round(summary.no_travel_miles, 1),
                    "eligible": summary.eligible,
                },
                "checkpoints": checkpoint_results,
                "_sort_key": rank_route_key(summary, route.duration_seconds),
            }
        )

    results.sort(key=lambda route: route["_sort_key"])
    for index, route in enumerate(results, start=1):
        route["rank"] = index
        route.pop("_sort_key")

    eligible = [route for route in results if route["risk_summary"]["eligible"]]
    recommendation = eligible[0]["id"] if eligible else None
    warnings = []
    if len(results) < 3:
        warnings.append(
            f"The routing provider returned {len(results)} distinct route option(s); "
            "three distinct routes were not available for this trip."
        )
    if recommendation is None:
        warnings.append("Every available route includes a No Travel weather segment.")

    return {
        "origin": {"label": origin.label, "longitude": origin.longitude, "latitude": origin.latitude},
        "destination": {
            "label": destination.label,
            "longitude": destination.longitude,
            "latitude": destination.latitude,
        },
        "departure_time": departure_time.isoformat(),
        "load_weight_lb": load_weight_lb,
        "checkpoint_interval_miles": checkpoint_interval_miles,
        "route_count": len(results),
        "required_route_count": 3,
        "recommendation_id": recommendation,
        "routes": results,
        "warnings": warnings,
        "weather_source": "WeatherAPI.com",
        "routing_source": "Mapbox Directions",
        "generated_at": timezone.now().isoformat(),
    }

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import urlencode

from django.conf import settings

from .http import ProviderError, get_json

METERS_PER_MILE = 1609.344
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class ResolvedLocation:
    label: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class CandidateRoute:
    route_id: str
    geometry: tuple[tuple[float, float], ...]
    segment_lengths_miles: tuple[float, ...]
    distance_miles: float
    duration_seconds: float
    strategy: str


def _token() -> str:
    value = getattr(settings, "MAPBOX_ACCESS_TOKEN", "")
    if not value:
        raise ProviderError("Mapbox is not configured. Set MAPBOX_ACCESS_TOKEN in the backend environment.")
    return value


def _distance_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(radians, a)
    lon2, lat2 = map(radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    haversine = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(min(1.0, haversine)))


def _interpolate(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    delta_lon = ((b[0] - a[0] + 180) % 360) - 180
    lon = ((a[0] + delta_lon * t + 180) % 360) - 180
    return lon, a[1] + (b[1] - a[1]) * t


def _sample_geometry(route: CandidateRoute, count: int = 64) -> tuple[tuple[float, float], ...]:
    points = route.geometry
    lengths = [_distance_miles(points[index], points[index + 1]) for index in range(len(points) - 1)]
    total = sum(lengths)
    if total <= 0:
        return points[:1]
    samples = []
    for sample_index in range(count):
        target = total * sample_index / (count - 1)
        traversed = 0.0
        for index, length in enumerate(lengths):
            if traversed + length >= target or index == len(lengths) - 1:
                ratio = 0.0 if length == 0 else (target - traversed) / length
                samples.append(_interpolate(points[index], points[index + 1], min(1.0, max(0.0, ratio))))
                break
            traversed += length
    return tuple(samples)


def _is_distinct(candidate: CandidateRoute, existing: list[CandidateRoute]) -> bool:
    candidate_samples = _sample_geometry(candidate)
    for route in existing:
        other_samples = _sample_geometry(route)
        if len(candidate_samples) != len(other_samples):
            continue
        matches = sum(
            _distance_miles(left, right) <= 0.25
            for left, right in zip(candidate_samples, other_samples)
        )
        if matches / len(candidate_samples) >= 0.90:
            return False
    return True


class MapboxProvider:
    """Geocoding and driving routes with bounded alternative-route attempts."""

    def __init__(self) -> None:
        self.access_token = _token()

    def geocode(self, query: str) -> ResolvedLocation:
        params = {"q": query, "limit": 1, "access_token": self.access_token}
        if settings.GEOCODING_COUNTRY:
            params["country"] = settings.GEOCODING_COUNTRY
        result: Any = get_json(
            f"https://api.mapbox.com/search/geocode/v6/forward?{urlencode(params)}"
        )
        features = result.get("features", []) if isinstance(result, dict) else []
        if not features:
            raise ProviderError(f"Could not find a location for '{query}'.")
        feature = features[0]
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) < 2:
            raise ProviderError(f"Geocoding returned no coordinates for '{query}'.")
        properties = feature.get("properties", {})
        label = properties.get("full_address") or properties.get("name") or query
        return ResolvedLocation(label, float(coordinates[0]), float(coordinates[1]))

    def suggest_locations(self, query: str) -> list[dict[str, str]]:
        params = {
            "q": query,
            "limit": 5,
            "autocomplete": "true",
            "permanent": "false",
            "access_token": self.access_token,
        }
        if settings.GEOCODING_COUNTRY:
            params["country"] = settings.GEOCODING_COUNTRY
        result: Any = get_json(
            f"https://api.mapbox.com/search/geocode/v6/forward?{urlencode(params)}"
        )
        features = result.get("features", []) if isinstance(result, dict) else []
        suggestions = []
        for feature in features:
            properties = feature.get("properties", {})
            label = properties.get("full_address") or properties.get("name")
            if not label:
                continue
            identifier = properties.get("mapbox_id") or feature.get("id") or label
            suggestions.append({"id": str(identifier), "label": str(label)})
        return suggestions

    def get_three_routes(
        self, origin: ResolvedLocation, destination: ResolvedLocation, departure_time: str
    ) -> tuple[CandidateRoute, ...]:
        """Request three distinct candidates, retrying with road exclusions as needed."""
        coordinates = (
            f"{origin.longitude},{origin.latitude};"
            f"{destination.longitude},{destination.latitude}"
        )
        strategies = (("standard", None), ("avoid-tolls", "toll"), ("avoid-motorways", "motorway"), ("avoid-ferries", "ferry"))
        candidates: list[CandidateRoute] = []
        saw_response = False
        for strategy, exclusion in strategies:
            params = {
                "alternatives": "true",
                "overview": "full",
                "geometries": "geojson",
                "annotations": "distance",
                "steps": "false",
                "depart_at": departure_time,
                "access_token": self.access_token,
            }
            if exclusion:
                params["exclude"] = exclusion
            url = (
                "https://api.mapbox.com/directions/v5/mapbox/driving-traffic/"
                f"{coordinates}.json?{urlencode(params)}"
            )
            payload: Any = get_json(url)
            if not isinstance(payload, dict):
                continue
            saw_response = True
            if payload.get("code") not in (None, "Ok"):
                if not candidates:
                    raise ProviderError(payload.get("message", "Routing provider could not build a route."))
                continue
            for index, result in enumerate(payload.get("routes", [])):
                raw_coordinates = result.get("geometry", {}).get("coordinates", [])
                if len(raw_coordinates) < 2:
                    continue
                geometry = tuple((float(point[0]), float(point[1])) for point in raw_coordinates)
                if sum(
                    _distance_miles(geometry[segment], geometry[segment + 1])
                    for segment in range(len(geometry) - 1)
                ) <= 0:
                    continue
                distance = float(result.get("distance", 0)) / METERS_PER_MILE
                duration = float(result.get("duration", 0))
                if distance <= 0 or duration < 0:
                    continue
                annotation_distances = []
                for leg in result.get("legs", []):
                    annotation_distances.extend(
                        float(value) / METERS_PER_MILE
                        for value in leg.get("annotation", {}).get("distance", [])
                    )
                if len(annotation_distances) != len(geometry) - 1:
                    geometric_lengths = [
                        _distance_miles(geometry[segment], geometry[segment + 1])
                        for segment in range(len(geometry) - 1)
                    ]
                    geometric_total = sum(geometric_lengths)
                    if geometric_total <= 0:
                        continue
                    segment_lengths = tuple(
                        length * distance / geometric_total for length in geometric_lengths
                    )
                else:
                    segment_lengths = tuple(annotation_distances)
                    annotated_distance = sum(segment_lengths)
                    if annotated_distance > 0:
                        distance = annotated_distance
                route = CandidateRoute(
                    route_id=f"{strategy}-{index + 1}",
                    geometry=geometry,
                    segment_lengths_miles=segment_lengths,
                    distance_miles=distance,
                    duration_seconds=duration,
                    strategy=strategy,
                )
                if _is_distinct(route, candidates):
                    candidates.append(route)
                if len(candidates) == 3:
                    return tuple(candidates)

        if not candidates or not saw_response:
            raise ProviderError("The routing provider returned no usable route.")
        if len(candidates) != 3:
            raise ProviderError(
                f"Only {len(candidates)} distinct route option(s) are available for this trip. "
                "This planner requires three distinct routes; try another origin or destination."
            )
        return tuple(candidates)

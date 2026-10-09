"""Distance-based route checkpoint placement and proportional ETA estimates."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Sequence

EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class RouteCheckpoint:
    mile: float
    longitude: float
    latitude: float
    elapsed_seconds: float


def _segment_length_miles(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = map(radians, start)
    lon2, lat2 = map(radians, end)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    haversine = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(min(1.0, haversine)))


def _interpolate_coordinate(
    start: tuple[float, float], end: tuple[float, float], fraction: float
) -> tuple[float, float]:
    """Interpolate lon/lat, taking the shorter longitude path across the date line."""
    lon1, lat1 = start
    lon2, lat2 = end
    longitude_delta = ((lon2 - lon1 + 180) % 360) - 180
    longitude = ((lon1 + longitude_delta * fraction + 180) % 360) - 180
    latitude = lat1 + (lat2 - lat1) * fraction
    return longitude, latitude


def place_checkpoints(
    geometry: Sequence[tuple[float, float]],
    interval_miles: float,
    duration_seconds: float,
    segment_lengths_miles: Sequence[float] | None = None,
) -> tuple[RouteCheckpoint, ...]:
    """Place samples every interval plus both endpoints of a route geometry.

    Geometry uses (longitude, latitude) pairs. ETA is estimated by assigning
    route duration in proportion to distance traveled, as specified in the plan.
    """
    if len(geometry) < 2:
        raise ValueError("Route geometry must contain at least two coordinates")
    interval = float(interval_miles)
    duration = float(duration_seconds)
    if not isfinite(interval) or interval <= 0:
        raise ValueError("interval_miles must be a finite, positive number")
    if not isfinite(duration) or duration < 0:
        raise ValueError("duration_seconds must be a finite, non-negative number")

    coordinates = []
    for longitude, latitude in geometry:
        longitude = float(longitude)
        latitude = float(latitude)
        if not isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees")
        if not isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees")
        coordinates.append((longitude, latitude))

    if segment_lengths_miles is not None and len(segment_lengths_miles) != len(coordinates) - 1:
        raise ValueError("Segment distances must match the route geometry")

    segments = []
    cumulative = [0.0]
    for index, (start, end) in enumerate(zip(coordinates, coordinates[1:])):
        length = (
            float(segment_lengths_miles[index])
            if segment_lengths_miles is not None
            else _segment_length_miles(start, end)
        )
        if not isfinite(length) or length < 0:
            raise ValueError("Segment distances must be finite and non-negative")
        segments.append((start, end, cumulative[-1], length))
        cumulative.append(cumulative[-1] + length)
    total = cumulative[-1]
    if total <= 0:
        raise ValueError("Route geometry must have a positive length")

    distances = [0.0]
    distance = interval
    while distance < total:
        distances.append(distance)
        distance += interval
    distances.append(total)

    checkpoints = []
    segment_index = 0
    for mile in distances:
        while segment_index < len(segments) - 1 and cumulative[segment_index + 1] < mile:
            segment_index += 1
        start, end, segment_start, segment_length = segments[segment_index]
        if mile >= total:
            longitude, latitude = coordinates[-1]
        elif segment_length == 0:
            longitude, latitude = end
        else:
            longitude, latitude = _interpolate_coordinate(
                start, end, (mile - segment_start) / segment_length
            )
        checkpoints.append(
            RouteCheckpoint(
                mile=mile,
                longitude=longitude,
                latitude=latitude,
                elapsed_seconds=duration * mile / total,
            )
        )
    return tuple(checkpoints)

"""Deterministic implementation of the weather and load thresholds in the brief."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import isfinite
from typing import Iterable


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4


@dataclass(frozen=True)
class WeatherReading:
    wind_mph: float
    rain_in_per_hour: float
    snow_in_per_hour: float


@dataclass(frozen=True)
class CheckpointRisk:
    level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_adjustment: RiskLevel | None


@dataclass(frozen=True)
class RouteRiskSummary:
    severe_miles: float
    high_miles: float
    average_risk: float
    no_travel_miles: float

    @property
    def eligible(self) -> bool:
        return self.no_travel_miles == 0


def _validate_measurement(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number")
    return value


def _band(value: float, boundaries: tuple[float, float, float, float], *,
          last_inclusive: bool = False) -> RiskLevel:
    low_mod, mod_high, high_severe, severe_stop = boundaries
    if value < low_mod:
        return RiskLevel.LOW
    if value < mod_high:
        return RiskLevel.MODERATE
    if value < high_severe:
        return RiskLevel.HIGH
    stays_severe = value <= severe_stop if last_inclusive else value < severe_stop
    if stays_severe:
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def classify_checkpoint(reading: WeatherReading, load_lb: float) -> CheckpointRisk:
    """Classify one forecast sample; the worst hazard determines checkpoint risk."""
    wind = _validate_measurement("wind_mph", reading.wind_mph)
    rain = _validate_measurement("rain_in_per_hour", reading.rain_in_per_hour)
    snow = _validate_measurement("snow_in_per_hour", reading.snow_in_per_hour)
    load = _validate_measurement("load_lb", load_lb)

    wind_level = _band(wind, (25, 35, 45, 55))
    rain_level = _band(rain, (0.10, 0.25, 0.50, 1.00), last_inclusive=True)
    snow_level = _band(snow, (0.5, 1.0, 2.0, 3.0), last_inclusive=True)

    # Rain and snow stay Severe at 1.00 and 3.00; wind reaches No Travel at 55.
    load_adjustment = None
    if 45 <= wind < 55 and load > 30_000:
        load_adjustment = RiskLevel.NO_TRAVEL
    elif 35 <= wind < 45 and load > 40_000:
        load_adjustment = RiskLevel.SEVERE

    contributors = [wind_level, rain_level, snow_level]
    if load_adjustment is not None:
        contributors.append(load_adjustment)
    return CheckpointRisk(
        level=max(contributors),
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_adjustment=load_adjustment,
    )


def summarize_route_risk(
    route_length_miles: float,
    samples: Iterable[tuple[float, RiskLevel]],
) -> RouteRiskSummary:
    """Weight checkpoint categories by the nearest route segment in miles.

    Sample points are sorted by route mile. Segment boundaries are halfway
    between samples; the first and last samples extend to route endpoints.
    """
    length = _validate_measurement("route_length_miles", route_length_miles)
    points = sorted((float(mile), RiskLevel(level)) for mile, level in samples)
    if not points:
        raise ValueError("At least one checkpoint risk sample is required")
    if any(not isfinite(mile) or mile < 0 or mile > length for mile, _ in points):
        raise ValueError("Checkpoint miles must be finite and within the route")
    if any(points[index][0] == points[index - 1][0] for index in range(1, len(points))):
        raise ValueError("Checkpoint mile markers must be distinct")

    boundaries = [0.0]
    boundaries.extend((points[i - 1][0] + points[i][0]) / 2 for i in range(1, len(points)))
    boundaries.append(length)

    totals = {level: 0.0 for level in RiskLevel}
    for index, (_, level) in enumerate(points):
        totals[level] += max(0.0, boundaries[index + 1] - boundaries[index])

    if length == 0:
        average = float(points[0][1])
    else:
        average = sum(float(level) * miles for level, miles in totals.items()) / length
    return RouteRiskSummary(
        severe_miles=totals[RiskLevel.SEVERE],
        high_miles=totals[RiskLevel.HIGH],
        average_risk=average,
        no_travel_miles=totals[RiskLevel.NO_TRAVEL],
    )


def rank_route_key(summary: RouteRiskSummary, duration_seconds: float) -> tuple[float, ...]:
    """Sort key matching the brief. No Travel routes sort after eligible routes."""
    duration = _validate_measurement("duration_seconds", duration_seconds)
    return (
        0.0 if summary.eligible else 1.0,
        summary.severe_miles,
        summary.high_miles,
        summary.average_risk,
        duration,
    )

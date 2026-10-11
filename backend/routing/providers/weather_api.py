from __future__ import annotations

from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from typing import Any, Sequence
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

from ..domain.risk import WeatherReading
from .http import ProviderError, get_json

FORECAST_DAYS = 3
MAX_CONCURRENT_REQUESTS = 4
WEATHER_CACHE_TTL_SECONDS = 3 * 60 * 60
FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"


class ForecastWindowError(ProviderError):
    """A requested time is outside the forecast window available to this plan."""


def _cached_get_json(url: str) -> Any:
    key = "weatherapi:" + sha256(url.encode("utf-8")).hexdigest()
    response = cache.get(key)
    if response is not None:
        return response
    response = get_json(url, timeout_seconds=20)
    cache.set(key, response, timeout=WEATHER_CACHE_TTL_SECONDS)
    return response


def _number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ProviderError(f"WeatherAPI.com did not return a valid {field}.") from error
    if not isfinite(number) or number < 0:
        raise ProviderError(f"WeatherAPI.com returned an invalid {field} value.")
    return number


def _hourly_forecast(payload: Any) -> tuple[tuple[int, float, float, float], ...]:
    if not isinstance(payload, dict):
        raise ProviderError("WeatherAPI.com returned an unexpected forecast response.")
    if "error" in payload:
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else None
        raise ProviderError(message or "WeatherAPI.com could not return a forecast.")

    forecast = payload.get("forecast")
    days = forecast.get("forecastday", []) if isinstance(forecast, dict) else []
    hours = []
    for day in days:
        if not isinstance(day, dict):
            continue
        for hour in day.get("hour", []):
            if not isinstance(hour, dict):
                continue
            try:
                timestamp = int(hour["time_epoch"])
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderError("WeatherAPI.com returned an invalid hourly timestamp.") from error
            hours.append(
                (
                    timestamp,
                    _number(hour.get("wind_mph"), "wind speed"),
                    _number(hour.get("precip_in"), "precipitation"),
                    _number(hour.get("snow_cm"), "snowfall") / 2.54,
                )
            )
    if not hours:
        raise ProviderError("WeatherAPI.com returned no hourly forecast.")
    return tuple(sorted(hours, key=lambda item: item[0]))


def _at_arrival(
    hours: tuple[tuple[int, float, float, float], ...],
    arrival_timestamp: float,
) -> WeatherReading:
    timestamps = [hour[0] for hour in hours]
    left = bisect_right(timestamps, arrival_timestamp) - 1
    if left < 0 or left >= len(hours) or arrival_timestamp > timestamps[-1]:
        raise ForecastWindowError(
            "WeatherAPI.com's free plan provides a 3-day forecast. This trip has a "
            "checkpoint outside that window. Choose an earlier departure or a shorter trip."
        )

    right = min(left + 1, len(hours) - 1)
    wind_left = hours[left][1]
    wind_right = hours[right][1]
    span = timestamps[right] - timestamps[left]
    fraction = 0 if span <= 0 else (arrival_timestamp - timestamps[left]) / span
    wind = wind_left + (wind_right - wind_left) * fraction

    # Use the precipitation values for the hourly interval containing the ETA.
    return WeatherReading(
        wind_mph=wind,
        rain_in_per_hour=hours[left][2],
        snow_in_per_hour=hours[left][3],
    )


class WeatherApiProvider:
    def fetch_at(
        self,
        locations: Sequence[tuple[float, float, datetime]],
        *,
        now: datetime | None = None,
    ) -> tuple[WeatherReading, ...]:
        if not locations:
            return ()
        api_key = getattr(settings, "WEATHERAPI_API_KEY", "").strip()
        if not api_key:
            raise ProviderError(
                "WeatherAPI.com is not configured. Set WEATHERAPI_API_KEY in the backend environment."
            )

        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("now must include a timezone")
        grouped: dict[tuple[str, str], list[tuple[int, datetime]]] = {}
        for index, (longitude, latitude, arrival) in enumerate(locations):
            if arrival.tzinfo is None:
                raise ValueError("arrival times must include a timezone")
            coordinate = (f"{latitude:.6f}", f"{longitude:.6f}")
            grouped.setdefault(coordinate, []).append((index, arrival.astimezone(UTC)))

        def fetch_forecast(coordinate: tuple[str, str]):
            latitude, longitude = coordinate
            params = {
                "key": api_key,
                "q": f"{latitude},{longitude}",
                "days": str(FORECAST_DAYS),
                "aqi": "no",
                "alerts": "no",
                "hour_fields": "time_epoch,wind_mph,precip_in,snow_cm",
            }
            payload = _cached_get_json(f"{FORECAST_URL}?{urlencode(params)}")
            return _hourly_forecast(payload)

        coordinates = list(grouped)
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
            forecasts = dict(zip(coordinates, pool.map(fetch_forecast, coordinates)))

        readings: list[WeatherReading | None] = [None] * len(locations)
        for coordinate, indexed_arrivals in grouped.items():
            hours = forecasts[coordinate]
            latest_arrival = max(arrival.timestamp() for _, arrival in indexed_arrivals)
            # Check each coordinate's latest requested checkpoint before building results.
            _at_arrival(hours, latest_arrival)
            for index, arrival in indexed_arrivals:
                readings[index] = _at_arrival(hours, arrival.timestamp())

        if any(reading is None for reading in readings):
            raise ProviderError("WeatherAPI.com did not return every requested checkpoint.")
        return tuple(reading for reading in readings if reading is not None)

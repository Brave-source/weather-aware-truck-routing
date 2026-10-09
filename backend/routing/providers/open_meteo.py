from __future__ import annotations

from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import ceil, isfinite
from typing import Any, Sequence
from urllib.parse import urlencode

from django.conf import settings

from ..domain.risk import WeatherReading
from .http import ProviderError, get_json

MAX_FORECAST_HOURS = 16 * 24
LOCATION_BATCH_SIZE = 40
MAX_CONCURRENT_REQUESTS = 8


def _number(value: Any, field: str) -> float:
    if value is None:
        raise ProviderError(f"The weather provider did not return {field} for a checkpoint.")
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ProviderError(f"The weather provider returned an invalid {field} value.")
    return value


def _at_arrival(hourly: dict[str, Any], arrival_timestamp: float) -> WeatherReading:
    times = hourly.get("time", [])
    if not times:
        raise ProviderError("The weather provider returned no hourly forecast timeline.")
    timestamps = [int(value) for value in times]
    left = bisect_right(timestamps, arrival_timestamp) - 1
    if left < 0 or left >= len(timestamps):
        raise ProviderError("A checkpoint ETA falls outside the available weather forecast.")
    right = min(left + 1, len(timestamps) - 1)
    if arrival_timestamp > timestamps[-1]:
        raise ProviderError("A checkpoint ETA falls outside the available weather forecast.")

    winds = hourly.get("wind_speed_10m", [])
    rains = hourly.get("rain", [])
    snows = hourly.get("snowfall", [])
    if any(len(series) <= right for series in (winds, rains, snows)):
        raise ProviderError("The weather provider returned an incomplete checkpoint forecast.")

    wind_left = _number(winds[left], "wind speed")
    wind_right = _number(winds[right], "wind speed")
    span = timestamps[right] - timestamps[left]
    fraction = 0 if span <= 0 else (arrival_timestamp - timestamps[left]) / span
    wind = wind_left + (wind_right - wind_left) * fraction

    # Rain and snowfall are hourly accumulations for the hour ending at the
    # timestamp. For an ETA between timestamps, use the bucket ending at the
    # next timestamp so the selected accumulation covers the arrival hour.
    precipitation_index = left if arrival_timestamp == timestamps[left] else right
    rain = _number(rains[precipitation_index], "rainfall")
    snow = _number(snows[precipitation_index], "snowfall")
    return WeatherReading(wind_mph=wind, rain_in_per_hour=rain, snow_in_per_hour=snow)


class OpenMeteoProvider:
    """Retrieve global hourly forecast samples in location batches."""

    def fetch_at(
        self,
        locations: Sequence[tuple[float, float, datetime]],
        *,
        now: datetime | None = None,
        horizon_until: datetime | None = None,
    ) -> tuple[WeatherReading, ...]:
        if not locations:
            return ()
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("now must include a timezone")
        latest_arrival = max(arrival.astimezone(UTC) for _, _, arrival in locations)
        if horizon_until is not None:
            latest_arrival = max(latest_arrival, horizon_until.astimezone(UTC))
        current_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        forecast_hours = max(48, ceil((latest_arrival - current_hour).total_seconds() / 3600) + 2)
        if forecast_hours > MAX_FORECAST_HOURS:
            raise ProviderError("The latest checkpoint ETA is beyond the provider's 16-day forecast horizon.")

        base_url = getattr(settings, "OPEN_METEO_API_BASE", "https://api.open-meteo.com/v1/forecast")
        api_key = getattr(settings, "OPEN_METEO_API_KEY", "")
        batches = [
            locations[start : start + LOCATION_BATCH_SIZE]
            for start in range(0, len(locations), LOCATION_BATCH_SIZE)
        ]

        def fetch_batch(batch):
            params = {
                "latitude": ",".join(f"{latitude:.6f}" for _, latitude, _ in batch),
                "longitude": ",".join(f"{longitude:.6f}" for longitude, _, _ in batch),
                "hourly": "wind_speed_10m,rain,snowfall",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "UTC",
                "timeformat": "unixtime",
                "forecast_hours": str(forecast_hours),
            }
            if api_key:
                params["apikey"] = api_key
            response: Any = get_json(f"{base_url}?{urlencode(params)}", timeout_seconds=30)
            if isinstance(response, dict):
                result_locations = [response]
            elif isinstance(response, list):
                result_locations = response
            else:
                raise ProviderError("The weather provider returned an unexpected response.")
            if len(result_locations) != len(batch):
                raise ProviderError("The weather provider returned a different number of checkpoint forecasts than requested.")
            batch_readings = []
            for weather_data, (_, _, arrival) in zip(result_locations, batch):
                if not isinstance(weather_data, dict):
                    raise ProviderError("The weather provider returned an invalid checkpoint forecast.")
                batch_readings.append(
                    _at_arrival(weather_data.get("hourly", {}), arrival.astimezone(UTC).timestamp())
                )
            return batch_readings

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
            batch_readings = pool.map(fetch_batch, batches)
            return tuple(reading for result in batch_readings for reading in result)

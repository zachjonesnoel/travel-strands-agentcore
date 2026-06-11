"""Weather tools backed by the free Open-Meteo API (no API key required)."""

import logging

import httpx
from strands import tool

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = httpx.Timeout(15.0)

# WMO weather interpretation codes -> human-readable description.
_WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _describe(code: int) -> str:
    return _WMO.get(int(code), f"Unknown (code {code})")


def _geocode(city: str) -> dict | None:
    """Resolve a city name to coordinates via Open-Meteo geocoding."""
    resp = httpx.get(
        GEOCODE_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    return results[0] if results else None


@tool
def get_weather(city: str) -> str:
    """Get current weather conditions for a city.

    Args:
        city: City name, e.g. "Tokyo" or "Paris, France".

    Returns:
        A short description of current temperature and conditions.
    """
    try:
        loc = _geocode(city)
        if not loc:
            return f"Could not find a location matching '{city}'."

        resp = httpx.get(
            FORECAST_URL,
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        cur = resp.json().get("current", {})
    except Exception as exc:
        logger.warning("get_weather failed for %r: %s", city, exc)
        return f"Weather lookup failed for '{city}': {exc}"

    place = f"{loc.get('name')}, {loc.get('country', '')}".strip(", ")
    return (
        f"Current weather in {place}: {_describe(cur.get('weather_code', -1))}, "
        f"{cur.get('temperature_2m')}°C (feels like {cur.get('apparent_temperature')}°C), "
        f"humidity {cur.get('relative_humidity_2m')}%, "
        f"wind {cur.get('wind_speed_10m')} km/h."
    )


@tool
def get_forecast(city: str, days: int = 5) -> str:
    """Get a multi-day daily weather forecast for a city.

    Args:
        city: City name, e.g. "Tokyo".
        days: Number of forecast days (1-16).

    Returns:
        A day-by-day forecast of high/low temperatures and conditions.
    """
    days = max(1, min(int(days), 16))
    try:
        loc = _geocode(city)
        if not loc:
            return f"Could not find a location matching '{city}'."

        resp = httpx.get(
            FORECAST_URL,
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
    except Exception as exc:
        logger.warning("get_forecast failed for %r: %s", city, exc)
        return f"Forecast lookup failed for '{city}': {exc}"

    dates = daily.get("time", [])
    if not dates:
        return f"No forecast data available for '{city}'."

    place = f"{loc.get('name')}, {loc.get('country', '')}".strip(", ")
    lines = [f"{days}-day forecast for {place}:"]
    for i, date in enumerate(dates):
        lines.append(
            f"  {date}: {_describe(daily['weather_code'][i])}, "
            f"{daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C, "
            f"precip chance {daily['precipitation_probability_max'][i]}%."
        )
    return "\n".join(lines)

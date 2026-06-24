"""
MARK III Reflex — Weather Module

Uses Open-Meteo (free, no API key) + ip-api.com for auto-location.
Caches responses for 30 minutes to avoid hammering the API.
"""
from __future__ import annotations

import re
import time
import threading
import logging
from typing import Optional

log = logging.getLogger("markiii.reflex.weather")

_CACHE_TTL_S = 1800   # 30 minutes
_cache_lock  = threading.Lock()
_cache: dict = {}     # {"lat": ..., "lon": ..., "city": ..., "data": ..., "ts": ...}

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bweather\b|\bhow'?s (it |the weather)?(outside|today)?\b", re.I),           "current"),
    (re.compile(r"\b(will it|is it going to) rain\b|\bneed (an )?umbrella\b|\brain today\b",   re.I), "rain"),
    (re.compile(r"\b(temperature|temp) (outside|today|right now)\b|\bhow (hot|cold) is it outside\b", re.I), "temperature"),
    (re.compile(r"\bforecast\b|\bweather (this week|tomorrow)\b",                               re.I), "forecast"),
    (re.compile(r"\bsunrise\b",                                                                 re.I), "sunrise"),
    (re.compile(r"\bsunset\b",                                                                  re.I), "sunset"),
    (re.compile(r"\bhumidity\b",                                                                re.I), "humidity"),
]

_WMO_CODES = {
    0:  "Clear sky",
    1:  "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain",  63: "Moderate rain",    65: "Heavy rain",
    71: "Slight snow",  73: "Moderate snow",    75: "Heavy snow",  77: "Snow grains",
    80: "Light showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            data = _get_weather_data()
            if data is None:
                return "Weather data unavailable right now."
            fn = globals().get(f"_fmt_{action}")
            if fn:
                return fn(data)
    return None


def _get_location() -> Optional[dict]:
    try:
        import requests
        r = requests.get("http://ip-api.com/json/", timeout=3)
        if r.status_code == 200:
            d = r.json()
            return {"lat": d["lat"], "lon": d["lon"], "city": d.get("city", "your area")}
    except Exception as e:
        log.debug("Location lookup failed: %s", e)
    return None


def _get_weather_data() -> Optional[dict]:
    with _cache_lock:
        if _cache and (time.time() - _cache.get("ts", 0)) < _CACHE_TTL_S:
            return _cache.get("data")

    loc = _get_location()
    if not loc:
        return None

    try:
        import requests
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={loc['lat']}&longitude={loc['lon']}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,"
            f"weather_code,wind_speed_10m,uv_index"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            f"precipitation_sum,sunrise,sunset,uv_index_max"
            f"&timezone=auto&forecast_days=2"
        )
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        payload = r.json()
        daily = payload.get("daily", {})
        uv_now   = payload["current"].get("uv_index", None)
        uv_max   = daily.get("uv_index_max", [None])[0]
        result = {
            "city":        loc["city"],
            "temp":        payload["current"]["temperature_2m"],
            "humidity":    payload["current"]["relative_humidity_2m"],
            "precip":      payload["current"]["precipitation"],
            "code":        payload["current"]["weather_code"],
            "wind":        payload["current"]["wind_speed_10m"],
            "condition":   _WMO_CODES.get(payload["current"]["weather_code"], "Unknown"),
            "uv_now":      uv_now,
            "uv_max":      uv_max,
            "sunrise":     daily["sunrise"][0].split("T")[1] if daily.get("sunrise") else None,
            "sunset":      daily["sunset"][0].split("T")[1]  if daily.get("sunset")  else None,
            "daily_precip": daily.get("precipitation_sum", [0])[0] or 0,
        }
        with _cache_lock:
            _cache["data"] = result
            _cache["ts"]   = time.time()
        log.info("Weather refreshed for %s", loc["city"])
        return result
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return None


def _uv_label(uv: float) -> str:
    if uv is None:     return ""
    if uv <= 2:        return f"UV {uv:.0f} — low"
    if uv <= 5:        return f"UV {uv:.0f} — moderate"
    if uv <= 7:        return f"UV {uv:.0f} — high, use sun protection"
    if uv <= 10:       return f"UV {uv:.0f} — very high, limit exposure"
    return             f"UV {uv:.0f} — extreme, avoid direct sun"


def _fmt_current(d: dict) -> str:
    uv   = d.get("uv_now") or d.get("uv_max")
    uv_s = f"  {_uv_label(uv)}." if uv is not None else ""
    return (
        f"{d['condition']} in {d['city']}. "
        f"{d['temp']:.0f} degrees, {d['humidity']:.0f} percent humidity.{uv_s}"
    )

def _fmt_temperature(d: dict) -> str:
    return f"It's {d['temp']:.0f} degrees Celsius outside in {d['city']}."

def _fmt_rain(d: dict) -> str:
    if d["daily_precip"] > 0.5:
        return f"Yes, {d['daily_precip']:.0f} mm of rain expected today. Bring an umbrella."
    return "No significant rain expected today."

def _fmt_humidity(d: dict) -> str:
    return f"Humidity is {d['humidity']:.0f} percent in {d['city']}."

def _fmt_sunrise(d: dict) -> str:
    if d.get("sunrise"):
        return f"Sunrise is at {d['sunrise']}."
    return "Sunrise time unavailable."

def _fmt_sunset(d: dict) -> str:
    if d.get("sunset"):
        return f"Sunset is at {d['sunset']}."
    return "Sunset time unavailable."

def _fmt_forecast(d: dict) -> str:
    return _fmt_current(d)


def refresh_background() -> None:
    """Trigger a background cache refresh."""
    threading.Thread(target=_get_weather_data, daemon=True).start()

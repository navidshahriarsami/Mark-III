"""
MARK III — Time Service

Source of truth for time, date, timezone queries.
The LLM never answers these — this module does.
All data is local. Zero API calls. Zero hallucination risk.
"""
from __future__ import annotations
import datetime
import re
from typing import Optional

_WORLD_CITIES: dict[str, str] = {
    "tokyo": "Asia/Tokyo",       "japan": "Asia/Tokyo",
    "sydney": "Australia/Sydney", "australia": "Australia/Sydney",
    "london": "Europe/London",   "uk": "Europe/London",
    "paris": "Europe/Paris",     "france": "Europe/Paris",
    "dubai": "Asia/Dubai",       "uae": "Asia/Dubai",
    "new york": "America/New_York", "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "dhaka": "Asia/Dhaka",       "bangladesh": "Asia/Dhaka",
    "kolkata": "Asia/Kolkata",   "india": "Asia/Kolkata",
    "singapore": "Asia/Singapore",
    "beijing": "Asia/Shanghai",  "china": "Asia/Shanghai",
    "seoul": "Asia/Seoul",       "korea": "Asia/Seoul",
    "berlin": "Europe/Berlin",   "germany": "Europe/Berlin",
    "moscow": "Europe/Moscow",   "russia": "Europe/Moscow",
    "toronto": "America/Toronto", "canada": "America/Toronto",
}


def get_time(timezone_hint: str = "") -> str:
    """Return current time, optionally for a specific city/timezone."""
    if timezone_hint:
        tz_key = timezone_hint.lower().strip()
        tz_name = _WORLD_CITIES.get(tz_key)
        if tz_name:
            try:
                import zoneinfo
                tz  = zoneinfo.ZoneInfo(tz_name)
                now = datetime.datetime.now(tz)
                city = timezone_hint.title()
                return f"It's {now.strftime('%I:%M %p')} in {city}."
            except Exception:
                pass
    now = datetime.datetime.now()
    return f"It's {now.strftime('%I:%M %p')}."


def get_date() -> str:
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def get_day() -> str:
    return f"Today is {datetime.datetime.now().strftime('%A')}."


def get_datetime_context() -> dict:
    """Return structured context for injecting into LLM prompts."""
    now = datetime.datetime.now()
    return {
        "time":     now.strftime("%I:%M %p"),
        "date":     now.strftime("%A, %B %d, %Y"),
        "day":      now.strftime("%A"),
        "month":    now.strftime("%B"),
        "year":     now.year,
        "hour":     now.hour,
        "iso":      now.isoformat(timespec="minutes"),
    }


_PATTERNS = [
    (re.compile(r"\bwhat('?s| is) (the )?time\b|\btime (now|right now)\b|\bwhat time is it\b", re.I), "time"),
    (re.compile(r"\btime in (?P<city>.+)", re.I), "world_time"),
    (re.compile(r"\bwhat('?s| is) (today'?s |the )?date\b|\bwhat day is (it|today)\b", re.I), "date"),
    (re.compile(r"\bwhat day (of the week)?\b|\bwhat'?s today\b", re.I), "day"),
]


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        m = pattern.search(text)
        if m:
            if action == "world_time":
                city = m.group("city").strip().rstrip("?.!")
                return get_time(city)
            elif action == "time":   return get_time()
            elif action == "date":   return get_date()
            elif action == "day":    return get_day()
    return None


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)

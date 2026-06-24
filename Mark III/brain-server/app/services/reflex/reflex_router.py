"""
MARK III Phase 15D — Core Reflex Router

Priority order (most specific first):
  1. System   — time, date, CPU, RAM, disk, battery, temperature, uptime
  2. Weather  — current, rain, forecast, sunrise, sunset
  3. Network  — internet, IP, WiFi, speed
  4. Device   — battery, connected devices
  5. Media    — Spotify, now playing, play/pause/skip
  6. Apps     — active window, running processes
  7. Calendar — schedule, events, reminders (stub)
  8. Memory   — goals, projects, recall

Returns ReflexResponse.miss() if no module handles the query.
The caller then passes the query to Qwen or Council.

Zero LLM calls in this layer.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.reflex.base import ReflexResponse

log = logging.getLogger("markiii.reflex")

# Lazy-loaded modules (import only when needed)
_modules_loaded = False
_system   = None
_weather  = None
_network  = None
_device   = None
_media    = None
_apps     = None
_calendar = None
_memory   = None
_presence = None


def _load_modules() -> None:
    global _modules_loaded, _system, _weather, _network, _device, _media, _apps, _calendar, _memory, _presence
    if _modules_loaded:
        return
    from app.services.reflex import (
        system_module, weather_module, network_module,
        device_module, media_module, application_module,
        calendar_module, memory_module, presence_module,
    )
    _system   = system_module
    _weather  = weather_module
    _network  = network_module
    _device   = device_module
    _media    = media_module
    _apps     = application_module
    _calendar = calendar_module
    _memory   = memory_module
    _presence = presence_module
    _modules_loaded = True


# Priority-ordered list of (module_object, source_name)
def _ordered_modules():
    return [
        (_system,   "system"),
        (_weather,  "weather"),
        (_network,  "network"),
        (_device,   "device"),
        (_media,    "media"),
        (_apps,     "apps"),
        (_calendar, "calendar"),
        (_memory,   "memory"),
        (_presence, "presence"),
    ]


def route(query: str) -> ReflexResponse:
    """
    Attempt to handle a voice query using local reflex modules.

    Returns ReflexResponse with handled=True and the response text if a module
    claimed the query, or ReflexResponse.miss() to pass to Qwen/Council.
    """
    _load_modules()
    t0 = time.monotonic()

    for module, source in _ordered_modules():
        if module is None:
            continue
        try:
            if module.can_handle(query):
                text = module.handle(query)
                ms   = (time.monotonic() - t0) * 1000
                if text:
                    log.info("Reflex(%s) %.0f ms — %r", source, ms, text[:60])
                    return ReflexResponse(
                        handled    = True,
                        text       = text,
                        confidence = 0.95,
                        source     = source,
                        latency_ms = ms,
                    )
        except Exception as e:
            log.warning("Reflex module %r failed: %s", source, e)

    ms = (time.monotonic() - t0) * 1000
    log.debug("Reflex miss (%.0f ms) — passing to Qwen", ms)
    return ReflexResponse.miss()


def warm_weather_cache() -> None:
    """Pre-warm weather cache at startup so first weather query is instant."""
    if _modules_loaded and _weather:
        _weather.refresh_background()

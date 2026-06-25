"""
MARK III Phase 18 — Integration Manager

Routes factual queries to the correct data service BEFORE reaching the LLM.

Priority order:
  1. Reflex modules  (system, weather, network, apps, media, presence)
  2. Integration services  (time, device, location, news, calendar)
  3. Qwen 7B local LLM  (conversation, reasoning, personality)
  4. Council  (complex multi-step, coding, deep research)

The LLM is NEVER the source of truth for:
  - Time / date
  - Weather
  - Battery / device status
  - Calendar events
  - Location
  - News headlines

The LLM provides: intent, conversation, reasoning, personality.
The services provide: facts, real-world data, truth.

Usage:
    from app.services.integrations.integration_manager import route
    result = route("What time is it in Tokyo?")
    if result.handled:
        answer = result.text   # factual answer, no LLM needed
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("markiii.integrations")


@dataclass
class IntegrationResult:
    handled:    bool
    text:       str
    source:     str     # which service handled it
    latency_ms: float
    language:   str = "en"

    @classmethod
    def miss(cls) -> "IntegrationResult":
        return cls(handled=False, text="", source="none", latency_ms=0.0)


def route(query: str, language_code: str = "en") -> IntegrationResult:
    """
    Attempt to answer the query from a factual data service.
    Returns IntegrationResult.miss() if no service can handle it.
    """
    t0 = time.monotonic()

    # ── 1. Time / date (always local, zero latency) ───────────────────
    try:
        from app.services.integrations.time_service import can_handle as t_can, handle as t_handle
        if t_can(query):
            answer = t_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(time) %.0fms — %r", ms, answer[:60])
                return IntegrationResult(True, answer, "time", ms, language_code)
    except Exception as e:
        log.debug("Time service error: %s", e)

    # ── 2. Reflex system module (CPU, RAM, GPU, disk, battery, uptime) ─
    try:
        from app.services.reflex.system_module import can_handle as s_can, handle as s_handle
        if s_can(query):
            answer = s_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(system) %.0fms — %r", ms, answer[:60])
                return IntegrationResult(True, answer, "system", ms, language_code)
    except Exception as e:
        log.debug("System module error: %s", e)

    # ── 3. Weather (cached, 30min refresh) ────────────────────────────
    try:
        from app.services.reflex.weather_module import can_handle as w_can, handle as w_handle
        if w_can(query):
            answer = w_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(weather) %.0fms — %r", ms, answer[:60])
                return IntegrationResult(True, answer, "weather", ms, language_code)
    except Exception as e:
        log.debug("Weather module error: %s", e)

    # ── 4. Network (IP, WiFi, internet status) ─────────────────────────
    try:
        from app.services.reflex.network_module import can_handle as n_can, handle as n_handle
        if n_can(query):
            answer = n_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(network) %.0fms", ms)
                return IntegrationResult(True, answer, "network", ms, language_code)
    except Exception as e:
        log.debug("Network module error: %s", e)

    # ── 5. Device mesh (battery, device status) ────────────────────────
    try:
        from app.services.reflex.presence_module import can_handle as p_can, handle as p_handle
        if p_can(query):
            answer = p_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(presence) %.0fms", ms)
                return IntegrationResult(True, answer, "device", ms, language_code)
    except Exception as e:
        log.debug("Presence module error: %s", e)

    # ── 6. Media (Spotify, now playing) ───────────────────────────────
    try:
        from app.services.reflex.media_module import can_handle as m_can, handle as m_handle
        if m_can(query):
            answer = m_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(media) %.0fms", ms)
                return IntegrationResult(True, answer, "media", ms, language_code)
    except Exception as e:
        log.debug("Media module error: %s", e)

    # ── 7. Applications (running apps, active window) ──────────────────
    try:
        from app.services.reflex.application_module import can_handle as a_can, handle as a_handle
        if a_can(query):
            answer = a_handle(query)
            if answer:
                ms = (time.monotonic() - t0) * 1000
                log.info("Integration(apps) %.0fms", ms)
                return IntegrationResult(True, answer, "apps", ms, language_code)
    except Exception as e:
        log.debug("Apps module error: %s", e)

    # No integration service handled this — pass to LLM
    ms = (time.monotonic() - t0) * 1000
    log.debug("Integration miss (%.0fms) — routing to LLM", ms)
    return IntegrationResult.miss()


def get_realworld_context() -> dict:
    """
    Build a factual context block to inject into every LLM prompt.
    This ensures the LLM never needs to guess time, date, or weather.
    """
    ctx: dict = {}
    try:
        from app.services.integrations.time_service import get_datetime_context
        ctx.update(get_datetime_context())
    except Exception:
        pass
    try:
        from app.services.reflex.weather_module import _get_weather_data
        wd = _get_weather_data()
        if wd:
            ctx["weather_condition"] = wd.get("condition", "")
            ctx["weather_temp_c"]    = wd.get("temp", "")
            ctx["weather_city"]      = wd.get("city", "")
    except Exception:
        pass
    return ctx

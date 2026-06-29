# ADR-0009 — Integration Manager as Source of Live Truth

**Status:** Accepted
**Date:** 2026-06-28

## Decision

All live factual data is sourced exclusively from the Integration Manager. The LLM never answers time, date, weather, battery, device status, or system metrics from its training data.

Integration Manager priority:
1. Time service (local clock, 0ms)
2. System module (psutil + LHM, <30ms)
3. Weather (Open-Meteo, 30-min cached)
4. Network (socket, <20ms)
5. Media (Windows Media Session API, <100ms)
6. Apps (psutil process list, <100ms)

## Why Not Store Live Data in Vector Memory?

Time, weather, and battery change constantly. A vector memory embedding from 30 minutes ago is already stale. These values must always be retrieved live, never from memory.

## Consequence

When asked "what time is it in Tokyo?", MARK queries the time service with tzdata. The response is always accurate. Qwen never guesses.

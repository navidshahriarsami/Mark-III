"""
MARK III — AI Provider Manager

Central registry for all reasoning providers.

Usage:
    mgr = get_provider_manager()
    provider = mgr.select(task_tier)
    response = await provider.generate_async(req)

Selection order (FAST/DEEP tiers):
    1. Preferred provider from settings.ai_preferred_provider
    2. Failover to next enabled+available provider
    3. If all fail → returns error response (MARK III continues without LLM)

Health checks run on demand (not on a background loop) to keep boot fast.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.config import settings
from .base_provider import (
    BaseProvider, GenerateRequest, GenerateResponse,
    ProviderHealth, ProviderName, TaskTier,
)
logger = logging.getLogger("markiii.ai.manager")

# Import each provider defensively so one missing package never kills the others.
try:
    from .claude_provider import ClaudeProvider as _ClaudeProvider
except ImportError as _e:
    logger.warning("Claude provider unavailable at import time: %s", _e)
    _ClaudeProvider = None

try:
    from .openai_provider import OpenAIProvider as _OpenAIProvider
except ImportError as _e:
    logger.warning("OpenAI provider unavailable at import time: %s", _e)
    _OpenAIProvider = None

try:
    from .openrouter_provider import OpenRouterProvider as _OpenRouterProvider
except ImportError as _e:
    logger.warning("OpenRouter provider unavailable at import time: %s", _e)
    _OpenRouterProvider = None

try:
    from .local_provider import LocalProvider as _LocalProvider
except ImportError as _e:
    logger.warning("Local provider unavailable at import time: %s", _e)
    _LocalProvider = None

# How long to cache a health check result before re-checking
_HEALTH_TTL = 120.0  # seconds


class ProviderManager:
    """
    Singleton registry. Holds one instance of each provider.
    Handles selection order and failover transparently.
    """

    def __init__(self) -> None:
        self._providers: dict[ProviderName, BaseProvider] = {}
        self._health_cache: dict[ProviderName, tuple[float, ProviderHealth]] = {}

        _candidate_map = {
            ProviderName.CLAUDE:     _ClaudeProvider,
            ProviderName.OPENAI:     _OpenAIProvider,
            ProviderName.OPENROUTER: _OpenRouterProvider,
            ProviderName.LOCAL:      _LocalProvider,
        }
        for pname, cls in _candidate_map.items():
            if cls is None:
                continue
            try:
                self._providers[pname] = cls()
            except Exception as exc:
                logger.warning("Provider %s failed to initialise: %s", pname.value, exc)

        logger.info(
            "Provider manager ready. Enabled: %s",
            [n.value for n, p in self._providers.items() if p.is_enabled()],
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, task_tier: TaskTier = TaskTier.FAST) -> BaseProvider:
        """
        Return the best available provider for the given tier.
        Never raises — callers receive an error response from the dummy
        provider returned when no real provider is available.
        """
        if task_tier == TaskTier.LOCAL:
            raise ValueError("LOCAL tier tasks must not call select() — handle them inline.")

        preferred = ProviderName(settings.ai_preferred_provider)
        order     = self._build_order(preferred)

        for name in order:
            p = self._providers.get(name)
            if p and p.is_enabled():
                return p

        # All providers disabled or unavailable
        logger.error("No AI providers enabled. Returning null provider.")
        return _NullProvider()

    def _build_order(self, preferred: ProviderName) -> list[ProviderName]:
        """Preferred first, then the rest in stable order."""
        rest = [n for n in [ProviderName.CLAUDE, ProviderName.OPENAI, ProviderName.OPENROUTER, ProviderName.LOCAL]
                if n != preferred]
        return [preferred] + rest

    # ------------------------------------------------------------------
    # Generation with automatic failover
    # ------------------------------------------------------------------

    async def generate(
        self,
        req: GenerateRequest,
        allow_fallback: bool = True,
    ) -> GenerateResponse:
        """
        Call the preferred provider; if it errors, try fallback providers.
        Returns the first successful response, or an error response if
        all fail (MARK III must never crash because an LLM is unavailable).
        """
        preferred  = ProviderName(settings.ai_preferred_provider)
        order      = self._build_order(preferred)
        last_error = "No providers available."

        for name in order:
            p = self._providers.get(name)
            if not p or not p.is_enabled():
                continue

            resp = await p.generate_async(req)
            if not resp.error:
                return resp

            last_error = resp.error
            logger.warning("Provider %s failed (%s). Trying fallback.", name.value, resp.error)

            if not allow_fallback:
                return resp

        return GenerateResponse(
            text="", provider=preferred, model="",
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
            error=f"All providers failed. Last error: {last_error}",
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_all(self) -> dict[str, dict]:
        """Return health status for every registered provider."""
        out = {}
        for name, provider in self._providers.items():
            # Use cache if fresh enough
            cached = self._health_cache.get(name)
            if cached and (time.time() - cached[0]) < _HEALTH_TTL:
                h = cached[1]
            else:
                h = await provider.health_check()
                self._health_cache[name] = (time.time(), h)

            out[name.value] = {
                "enabled":     h.enabled,
                "available":   h.available,
                "error":       h.error,
                "avg_latency": round(h.avg_latency, 1),
                "calls_total": h.calls_total,
                "calls_error": h.calls_error,
                "last_check":  h.last_check,
            }
        return out

    async def health_for(self, name: ProviderName) -> ProviderHealth:
        p = self._providers.get(name)
        if not p:
            return ProviderHealth(name=name, enabled=False, available=False, error="Unknown provider.")
        h = await p.health_check()
        self._health_cache[name] = (time.time(), h)
        return h

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def usage_summary(self) -> dict:
        """Return aggregate call counts across all providers."""
        total_calls = 0
        total_errors = 0
        for p in self._providers.values():
            if hasattr(p, "_health"):
                total_calls  += p._health.calls_total
                total_errors += p._health.calls_error
        return {
            "total_calls":  total_calls,
            "total_errors": total_errors,
            "providers":    {
                n.value: {
                    "calls": getattr(self._providers[n], "_health", ProviderHealth(n, False, False)).calls_total,
                }
                for n in self._providers
            }
        }


class _NullProvider(BaseProvider):
    """Returned when no real provider is available. Never crashes the caller."""

    name = ProviderName.CLAUDE

    def is_enabled(self) -> bool:
        return False

    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        return GenerateResponse(
            text="MARK III is operating without an AI reasoning provider. "
                 "Configure ANTHROPIC_API_KEY or OPENAI_API_KEY in .env to enable AI features.",
            provider=ProviderName.CLAUDE, model="none",
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
            error="No provider available.",
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            name=ProviderName.CLAUDE, enabled=False, available=False,
            error="No providers configured.",
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    return _manager

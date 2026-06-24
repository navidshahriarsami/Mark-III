"""
MARK III — Claude (Anthropic) Provider

Model selection:
  FAST tier → claude-haiku-4-5-20251001
  DEEP tier → claude-sonnet-4-6

`anthropic` is imported lazily inside _get_client() so that a missing
package never crashes the provider registry at startup.  The provider
will simply report disabled/unavailable if the package is absent.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.config import settings
from .base_provider import (
    BaseProvider, GenerateRequest, GenerateResponse,
    ProviderHealth, ProviderName, TaskTier,
)

logger = logging.getLogger("markiii.ai.claude")

_FAST_MODEL = "claude-haiku-4-5-20251001"
_DEEP_MODEL = "claude-sonnet-4-6"

_COSTS = {
    _FAST_MODEL: {"in": 0.80,  "out": 4.00},
    _DEEP_MODEL: {"in": 3.00,  "out": 15.00},
}


class ClaudeProvider(BaseProvider):
    name = ProviderName.CLAUDE

    def __init__(self) -> None:
        self._client: Optional[Any] = None   # anthropic.AsyncAnthropic, loaded lazily
        self._health = ProviderHealth(
            name      = ProviderName.CLAUDE,
            enabled   = bool(settings.anthropic_api_key),
            available = False,
        )

    def _get_client(self) -> Optional[Any]:
        if self._client is None:
            try:
                import anthropic as _anthropic
                self._client = _anthropic.AsyncAnthropic(
                    api_key = settings.anthropic_api_key,
                    timeout = settings.ai_timeout_seconds,
                )
            except ImportError:
                logger.debug(
                    "anthropic package not installed — Claude provider unavailable. "
                    "pip install anthropic  to enable it."
                )
                return None
        return self._client

    def is_enabled(self) -> bool:
        return bool(settings.anthropic_api_key)

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str = _FAST_MODEL) -> float:
        c = _COSTS.get(model, _COSTS[_FAST_MODEL])
        return (input_tokens * c["in"] + output_tokens * c["out"]) / 1_000_000

    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        if not self.is_enabled():
            return GenerateResponse(
                text="", provider=ProviderName.CLAUDE, model="",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error="Claude provider not configured (no API key).",
            )

        client = self._get_client()
        if client is None:
            return GenerateResponse(
                text="", provider=ProviderName.CLAUDE, model="",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error="anthropic package not installed.",
            )

        model = _DEEP_MODEL if req.task_tier == TaskTier.DEEP else _FAST_MODEL
        t0 = time.monotonic()

        try:
            msg = await client.messages.create(
                model       = model,
                max_tokens  = req.max_tokens,
                temperature = req.temperature,
                system      = req.system_prompt,
                messages    = [{"role": "user", "content": req.user_prompt}],
            )
            latency  = (time.monotonic() - t0) * 1000
            in_tok   = msg.usage.input_tokens
            out_tok  = msg.usage.output_tokens
            text     = msg.content[0].text if msg.content else ""
            cost     = self.estimate_cost(in_tok, out_tok, model)

            self._health.available   = True
            self._health.calls_total += 1
            self._health.avg_latency = (self._health.avg_latency * 0.9) + (latency * 0.1)
            self._health.last_check  = time.time()
            self._health.error       = None

            logger.info(
                "Claude  model=%s  task=%s  in=%d  out=%d  ms=%.0f  cost=$%.5f",
                model, req.task_label, in_tok, out_tok, latency, cost,
            )

            return GenerateResponse(
                text          = text,
                provider      = ProviderName.CLAUDE,
                model         = model,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = latency,
                cost_usd      = cost,
            )

        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            self._health.calls_error += 1
            self._health.error       = str(e)
            logger.error("Claude error: %s", e)
            return GenerateResponse(
                text="", provider=ProviderName.CLAUDE, model=model,
                input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=0,
                error=str(e),
            )

    async def health_check(self) -> ProviderHealth:
        if not self.is_enabled():
            self._health.enabled   = False
            self._health.available = False
            self._health.error     = "No API key configured."
            return self._health

        client = self._get_client()
        if client is None:
            self._health.enabled   = False
            self._health.available = False
            self._health.error     = "anthropic package not installed."
            return self._health

        try:
            t0 = time.monotonic()
            await client.messages.create(
                model      = _FAST_MODEL,
                max_tokens = 1,
                messages   = [{"role": "user", "content": "ping"}],
            )
            self._health.available   = True
            self._health.avg_latency = (time.monotonic() - t0) * 1000
            self._health.error       = None
        except Exception as e:
            self._health.available = False
            self._health.error     = str(e)

        self._health.last_check = time.time()
        return self._health

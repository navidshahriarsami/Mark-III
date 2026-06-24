"""
MARK III — OpenAI Provider

Model selection:
  FAST tier → gpt-4o-mini
  DEEP tier → gpt-4o

Cost estimates (USD per 1M tokens, mid-2025):
  gpt-4o-mini : input $0.15 / output $0.60
  gpt-4o      : input $2.50 / output $10.00
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import openai as _openai

from app.config import settings
from .base_provider import (
    BaseProvider, GenerateRequest, GenerateResponse,
    ProviderHealth, ProviderName, TaskTier,
)

logger = logging.getLogger("markiii.ai.openai")

_FAST_MODEL = "gpt-4o-mini"
_DEEP_MODEL = "gpt-4o"

_COSTS = {
    _FAST_MODEL: {"in": 0.15,  "out": 0.60},
    _DEEP_MODEL: {"in": 2.50,  "out": 10.00},
}


class OpenAIProvider(BaseProvider):
    name = ProviderName.OPENAI

    def __init__(self) -> None:
        self._client: Optional[_openai.AsyncOpenAI] = None
        self._health = ProviderHealth(
            name      = ProviderName.OPENAI,
            enabled   = bool(settings.openai_api_key),
            available = False,
        )

    def _get_client(self) -> _openai.AsyncOpenAI:
        if self._client is None:
            self._client = _openai.AsyncOpenAI(
                api_key = settings.openai_api_key,
                timeout = settings.ai_timeout_seconds,
            )
        return self._client

    def is_enabled(self) -> bool:
        return bool(settings.openai_api_key)

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str = _FAST_MODEL) -> float:
        c = _COSTS.get(model, _COSTS[_FAST_MODEL])
        return (input_tokens * c["in"] + output_tokens * c["out"]) / 1_000_000

    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        if not self.is_enabled():
            return GenerateResponse(
                text="", provider=ProviderName.OPENAI, model="",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error="OpenAI provider not configured (no API key).",
            )

        model  = _DEEP_MODEL if req.task_tier == TaskTier.DEEP else _FAST_MODEL
        client = self._get_client()
        t0     = time.monotonic()

        try:
            resp = await client.chat.completions.create(
                model       = model,
                max_tokens  = req.max_tokens,
                temperature = req.temperature,
                messages    = [
                    {"role": "system",  "content": req.system_prompt},
                    {"role": "user",    "content": req.user_prompt},
                ],
            )
            latency  = (time.monotonic() - t0) * 1000
            in_tok   = resp.usage.prompt_tokens
            out_tok  = resp.usage.completion_tokens
            text     = resp.choices[0].message.content or ""
            cost     = self.estimate_cost(in_tok, out_tok, model)

            self._health.available   = True
            self._health.calls_total += 1
            self._health.avg_latency = (self._health.avg_latency * 0.9) + (latency * 0.1)
            self._health.last_check  = time.time()
            self._health.error       = None

            logger.info(
                "OpenAI  model=%s  task=%s  in=%d  out=%d  ms=%.0f  cost=$%.5f",
                model, req.task_label, in_tok, out_tok, latency, cost,
            )

            return GenerateResponse(
                text          = text,
                provider      = ProviderName.OPENAI,
                model         = model,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = latency,
                cost_usd      = cost,
            )

        except _openai.APIStatusError as e:
            latency = (time.monotonic() - t0) * 1000
            self._health.calls_error += 1
            self._health.available   = e.status_code not in (401, 403)
            self._health.error       = f"HTTP {e.status_code}: {e.message}"
            logger.error("OpenAI API error: %s", e)
            return GenerateResponse(
                text="", provider=ProviderName.OPENAI, model=model,
                input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=0,
                error=self._health.error,
            )

        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            self._health.calls_error += 1
            self._health.error       = str(e)
            logger.error("OpenAI unexpected error: %s", e)
            return GenerateResponse(
                text="", provider=ProviderName.OPENAI, model=model,
                input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=0,
                error=str(e),
            )

    async def health_check(self) -> ProviderHealth:
        if not self.is_enabled():
            self._health.enabled   = False
            self._health.available = False
            self._health.error     = "No API key configured."
            return self._health

        try:
            client = self._get_client()
            t0     = time.monotonic()
            await client.chat.completions.create(
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

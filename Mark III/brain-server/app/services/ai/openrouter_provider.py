"""
MARK III — OpenRouter Provider

OpenRouter exposes an OpenAI-compatible API that proxies hundreds of models.
Used by the Cognitive Council to call specialist models:
  Reasoning  → deepseek/deepseek-r1
  Coding     → qwen/qwen-2.5-coder-32b-instruct
  Research   → meta-llama/llama-3.1-70b-instruct
  Planning   → nvidia/llama-3.1-nemotron-70b-instruct
  Fallback   → openrouter/auto

Model is specified via GenerateRequest.model_override.
FAST tier default : meta-llama/llama-3.2-3b-instruct  (free tier)
DEEP tier default : meta-llama/llama-3.1-70b-instruct

Cost tracking: OpenRouter returns usage.prompt_tokens / completion_tokens.
Actual cost depends on the routed model; we store 0.0 when unknown.

Docs: https://openrouter.ai/docs
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

logger = logging.getLogger("markiii.ai.openrouter")

_BASE_URL    = "https://openrouter.ai/api/v1"
_FAST_MODEL  = "openai/gpt-oss-120b:free"     # OpenInference, 99.98% uptime — used for health pings
_DEEP_MODEL  = "meta-llama/llama-3.3-70b-instruct:free"
_APP_NAME    = "MARK III"
_APP_URL     = "https://markiii.local"


class OpenRouterProvider(BaseProvider):
    name = ProviderName.OPENROUTER

    def __init__(self) -> None:
        self._client = None
        self._health = ProviderHealth(
            name    = ProviderName.OPENROUTER,
            enabled = bool(settings.openrouter_api_key),
            available = False,
        )

    def _get_client(self):
        if self._client is None:
            import openai as _openai
            self._client = _openai.AsyncOpenAI(
                base_url = _BASE_URL,
                api_key  = settings.openrouter_api_key or "no-key",
                default_headers = {
                    "HTTP-Referer": _APP_URL,
                    "X-Title":      _APP_NAME,
                },
                timeout = settings.ai_timeout_seconds,
            )
        return self._client

    def is_enabled(self) -> bool:
        return bool(settings.openrouter_api_key)

    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        if not self.is_enabled():
            return GenerateResponse(
                text="", provider=ProviderName.OPENROUTER, model="",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error="OpenRouter provider not configured (no API key).",
            )

        model  = req.model_override or (
            _DEEP_MODEL if req.task_tier == TaskTier.DEEP else _FAST_MODEL
        )
        client = self._get_client()
        t0     = time.monotonic()

        try:
            import openai as _openai
            resp = await client.chat.completions.create(
                model       = model,
                max_tokens  = req.max_tokens,
                temperature = req.temperature,
                messages    = [
                    {"role": "system", "content": req.system_prompt},
                    {"role": "user",   "content": req.user_prompt},
                ],
            )
            latency = (time.monotonic() - t0) * 1000
            in_tok  = resp.usage.prompt_tokens     if resp.usage else 0
            out_tok = resp.usage.completion_tokens if resp.usage else 0
            raw_text = resp.choices[0].message.content or "" if resp.choices else ""
            text     = raw_text.encode("utf-8", "replace").decode("utf-8")

            self._health.available    = True
            self._health.calls_total += 1
            self._health.avg_latency  = (self._health.avg_latency * 0.9) + (latency * 0.1)
            self._health.last_check   = time.time()
            self._health.error        = None

            logger.info(
                "OpenRouter  model=%s  task=%s  in=%d  out=%d  ms=%.0f",
                model, req.task_label, in_tok, out_tok, latency,
            )

            return GenerateResponse(
                text          = text,
                provider      = ProviderName.OPENROUTER,
                model         = model,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = latency,
                cost_usd      = 0.0,  # OpenRouter bills externally
            )

        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            self._health.calls_error += 1
            self._health.error        = str(e)
            logger.error("OpenRouter error model=%s: %s", model, e)
            return GenerateResponse(
                text="", provider=ProviderName.OPENROUTER, model=model,
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

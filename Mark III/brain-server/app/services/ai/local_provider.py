"""
MARK III — Local Model Provider

Targets any OpenAI-compatible local inference server.
Default: Ollama running at http://localhost:11434

Model selection:
  FAST tier → settings.local_fast_model  (default: llama3.2:3b)
  DEEP tier → settings.local_deep_model  (default: llama3.2:8b)

Cost: always $0.00 — local inference.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.config import settings
from .base_provider import (
    BaseProvider, GenerateRequest, GenerateResponse,
    ProviderHealth, ProviderName, TaskTier,
)

logger = logging.getLogger("markiii.ai.local")


class LocalProvider(BaseProvider):
    """
    Calls an Ollama-compatible /v1/chat/completions endpoint.
    No dependency on the openai SDK — plain httpx so it works even if
    the openai package is absent.
    """

    name = ProviderName.LOCAL

    def __init__(self) -> None:
        self._base_url = settings.local_model_url.rstrip("/")
        self._health   = ProviderHealth(
            name    = ProviderName.LOCAL,
            enabled = settings.local_model_enabled,
            available = False,
        )

    def is_enabled(self) -> bool:
        return settings.local_model_enabled

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0

    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        if not self.is_enabled():
            return GenerateResponse(
                text="", provider=ProviderName.LOCAL, model="",
                input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0,
                error="Local provider disabled in config.",
            )

        model = (
            settings.local_deep_model
            if req.task_tier == TaskTier.DEEP
            else settings.local_fast_model
        )
        t0 = time.monotonic()

        payload = {
            "model":       model,
            "max_tokens":  req.max_tokens,
            "temperature": req.temperature,
            "messages": [
                {"role": "system", "content": req.system_prompt},
                {"role": "user",   "content": req.user_prompt},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            latency  = (time.monotonic() - t0) * 1000
            text     = data["choices"][0]["message"]["content"]
            usage    = data.get("usage", {})
            in_tok   = usage.get("prompt_tokens",     0)
            out_tok  = usage.get("completion_tokens", 0)

            self._health.available   = True
            self._health.calls_total += 1
            self._health.avg_latency = (self._health.avg_latency * 0.9) + (latency * 0.1)
            self._health.error       = None
            self._health.last_check  = time.time()

            logger.info(
                "Local  model=%s  task=%s  in=%d  out=%d  ms=%.0f",
                model, req.task_label, in_tok, out_tok, latency,
            )

            return GenerateResponse(
                text          = text,
                provider      = ProviderName.LOCAL,
                model         = model,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = latency,
                cost_usd      = 0.0,
            )

        except httpx.ConnectError:
            latency = (time.monotonic() - t0) * 1000
            self._health.available = False
            self._health.error     = f"Cannot reach local model at {self._base_url}"
            self._health.calls_error += 1
            return GenerateResponse(
                text="", provider=ProviderName.LOCAL, model=model,
                input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=0,
                error=self._health.error,
            )

        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            self._health.calls_error += 1
            self._health.error = str(e)
            logger.error("Local provider error: %s", e)
            return GenerateResponse(
                text="", provider=ProviderName.LOCAL, model=model,
                input_tokens=0, output_tokens=0, latency_ms=latency, cost_usd=0,
                error=str(e),
            )

    async def health_check(self) -> ProviderHealth:
        if not self.is_enabled():
            self._health.enabled   = False
            self._health.available = False
            self._health.error     = "Local provider disabled."
            return self._health

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/v1/models")
                resp.raise_for_status()
            self._health.available = True
            self._health.error     = None
        except Exception as e:
            self._health.available = False
            self._health.error     = str(e)

        self._health.last_check = time.time()
        return self._health

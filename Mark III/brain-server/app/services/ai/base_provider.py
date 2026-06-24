"""
MARK III — AI Provider Base Interface

Every external reasoning provider (Claude, OpenAI, local model) implements
this interface so the rest of the system never depends on a specific vendor.

MARK III owns the context, memory, goals, and decisions.
LLM providers supply reasoning on demand.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProviderName(str, Enum):
    CLAUDE      = "claude"
    OPENAI      = "openai"
    OPENROUTER  = "openrouter"
    LOCAL       = "local"


class TaskTier(str, Enum):
    """
    MARK III task routing tiers.
    LOCAL  — handled entirely by MARK III rules; no LLM call.
    FAST   — quick generation: daily summary, simple advice, short answers.
    DEEP   — high-quality analysis: weekly review, career guidance, goal analysis.
    """
    LOCAL = "local"
    FAST  = "fast"
    DEEP  = "deep"


@dataclass
class GenerateRequest:
    """Unified request passed to any provider."""
    system_prompt:  str
    user_prompt:    str
    task_tier:      TaskTier       = TaskTier.FAST
    max_tokens:     int            = 1024
    temperature:    float          = 0.4
    task_label:     str            = "generic"
    device_id:      str            = ""
    model_override: Optional[str]  = None  # forces a specific model, bypassing tier selection


@dataclass
class GenerateResponse:
    """Unified response from any provider."""
    text:           str
    provider:       ProviderName
    model:          str
    input_tokens:   int
    output_tokens:  int
    latency_ms:     float
    cost_usd:       float
    cached:         bool  = False
    error:          Optional[str] = None


@dataclass
class ProviderHealth:
    name:        ProviderName
    enabled:     bool
    available:   bool
    last_check:  float        = field(default_factory=time.time)
    error:       Optional[str] = None
    avg_latency: float         = 0.0
    calls_total: int           = 0
    calls_error: int           = 0


class BaseProvider(ABC):
    """
    Abstract base for all MARK III reasoning providers.

    Subclasses implement `generate_async` only.
    Timeout, error wrapping, and health tracking happen here.
    """

    name: ProviderName

    @abstractmethod
    async def generate_async(self, req: GenerateRequest) -> GenerateResponse:
        """Call the external model and return a structured response."""
        ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Return current health and availability of this provider."""
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return False if the provider is disabled in config or has no API key."""
        ...

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Override in subclass to provide accurate cost estimation."""
        return 0.0

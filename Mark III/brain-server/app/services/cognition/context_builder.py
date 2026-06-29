"""
MARK III — Context Builder

Assembles a unified context package from all available sources
before passing it to Qwen. The LLM receives a pre-built context,
not raw queries. It reasons — it does not retrieve.

Context package structure:
  {
    "query": "original user query",
    "intent": "conversation | reasoning | complex | recall ...",
    "language": "en",
    "datetime": { time, date, day, hour },
    "weather": { condition, temp, city, uv },
    "device": { active, battery, mesh_status },
    "memory_context": "retrieved from vector/obsidian",
    "session_summary": "recent conversation turns",
    "active_device": "desktop | macbook | iphone",
  }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.cognition.intent_classifier import Intent, IntentResult

log = logging.getLogger("markiii.cognition.context")


@dataclass
class ContextPackage:
    query:          str
    intent:         str
    language:       str    = "en"
    datetime_ctx:   dict   = field(default_factory=dict)
    weather_ctx:    dict   = field(default_factory=dict)
    device_ctx:     dict   = field(default_factory=dict)
    memory_context: str    = ""
    session_summary: str   = ""
    active_device:  str    = "desktop"
    direct_answer:  Optional[str] = None   # set if memory can answer directly
    direct_score:   float  = 0.0

    def to_prompt_string(self) -> str:
        """Convert context package to a string for injection into Qwen."""
        parts = []
        if self.datetime_ctx:
            parts.append(f"Current time: {self.datetime_ctx.get('time', '')} — {self.datetime_ctx.get('date', '')}")
        if self.weather_ctx:
            parts.append(f"Weather: {self.weather_ctx.get('condition', '')} {self.weather_ctx.get('temp', '')}°C in {self.weather_ctx.get('city', '')}")
        if self.device_ctx:
            parts.append(f"Active device: {self.active_device}")
        if self.memory_context:
            parts.append(f"MARK MEMORY:\n{self.memory_context}")
        return "\n".join(parts)


# ─── Builder ──────────────────────────────────────────────────────────────────

def build_context(
    query:  str,
    intent: IntentResult,
    top_k_memory: int = 3,
    memory_min_score: float = 0.45,
    direct_threshold: float = 0.75,
) -> ContextPackage:
    """
    Build the full context package for a query.

    Sources queried depend on intent:
    - FACTUAL_LIVE  → Integration Manager only
    - RECALL        → Memory (ChromaDB + SQLite) first, then Integration
    - CONVERSATION  → Memory + datetime context
    - REASONING     → Memory + all context
    - COMPLEX       → Everything
    """
    pkg = ContextPackage(query=query, intent=intent.intent.value)

    # ── Language ──────────────────────────────────────────────────────────────
    try:
        from app.services.integrations.language_service import get_current
        lang = get_current()
        pkg.language = lang.code
    except Exception:
        pass

    # ── Active device ─────────────────────────────────────────────────────────
    try:
        from app.services.voice.always_listening_loop import get_active_voice_device
        pkg.active_device = get_active_voice_device()
    except Exception:
        pass

    # ── DateTime (always include — cheap, zero API cost) ──────────────────────
    try:
        from app.services.integrations.time_service import get_datetime_context
        pkg.datetime_ctx = get_datetime_context()
    except Exception:
        pass

    # ── Weather (include for reasoning/complex queries) ────────────────────────
    if intent.intent in (Intent.REASONING, Intent.COMPLEX, Intent.CONVERSATION):
        try:
            from app.services.reflex.weather_module import _get_weather_data
            wd = _get_weather_data()
            if wd:
                pkg.weather_ctx = {
                    "condition": wd.get("condition", ""),
                    "temp":      wd.get("temp", ""),
                    "city":      wd.get("city", ""),
                    "uv":        wd.get("uv_max", ""),
                }
        except Exception:
            pass

    # ── Memory retrieval (skip for pure social/factual_live) ──────────────────
    if intent.intent not in (Intent.SOCIAL, Intent.FACTUAL_LIVE):
        _add_memory_context(pkg, query, top_k_memory, memory_min_score, direct_threshold)

    return pkg


def _add_memory_context(
    pkg:              ContextPackage,
    query:            str,
    top_k:            int,
    min_score:        float,
    direct_threshold: float,
) -> None:
    """Query ChromaDB and SQLite, check for direct answer, build memory string."""
    memories = []

    # 1. ChromaDB (primary)
    try:
        from app.services.memory.chroma_store import get_chroma_store
        results = get_chroma_store().search(query, top_k=top_k, min_score=min_score)
        for r in results:
            memories.append((r.score, r.content, r.source))
            if r.score >= direct_threshold and not pkg.direct_answer:
                pkg.direct_answer = r.content
                pkg.direct_score  = r.score
                log.info("Direct answer found (%.2f) from %s", r.score, r.source)
    except Exception as e:
        log.debug("ChromaDB recall error: %s", e)

    # 2. SQLite fallback (if ChromaDB empty or low score)
    if not memories or (memories and memories[0][0] < min_score + 0.1):
        try:
            from app.services.memory.vector_store import get_memory_store
            for m in get_memory_store().recall(query, top_k=top_k, min_score=min_score):
                memories.append((m.score, m.content, "sqlite"))
                if m.score >= direct_threshold and not pkg.direct_answer:
                    pkg.direct_answer = m.content
                    pkg.direct_score  = m.score
        except Exception as e:
            log.debug("SQLite recall error: %s", e)

    if memories:
        memories.sort(key=lambda x: x[0], reverse=True)
        pkg.memory_context = "\n".join(f"- {c}" for _, c, _ in memories[:top_k])

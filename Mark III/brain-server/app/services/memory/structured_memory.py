"""
MARK III — Structured Memory

High-level API for the authoritative fact system.
Called by the voice loop and query_council.

Usage:
    from app.services.memory.structured_memory import remember, recall_fact, get_facts

    remember("Project Orphans", "budget", "10 thousand dollars AUD")
    result = recall_fact("what is the Project Orphans budget?")
    if result.found:
        return result.answer  # bypass LLM
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.memory.fact_store    import get_fact_store, Fact
from app.services.memory.fact_extractor import extract_facts, should_extract
from app.services.memory.fact_normalizer import normalize
from app.services.memory.recall_engine  import recall, RecallResult, is_fact_query

log = logging.getLogger("markiii.memory.structured")


def remember(
    subject:    str,
    predicate:  str,
    raw_value:  str,
    confidence: float = 1.0,
    confirmed:  bool  = True,
    source:     str   = "voice",
) -> Fact:
    """
    Store a fact explicitly.
    Normalizes the value before storage.
    """
    norm = normalize(raw_value)
    fact = get_fact_store().upsert(
        subject    = subject,
        predicate  = predicate,
        value      = norm.value,
        raw_value  = raw_value,
        unit       = norm.unit,
        confidence = confidence,
        confirmed  = confirmed,
        source     = source,
    )
    log.info("Remembered: %s", fact.display())
    return fact


def process_utterance(text: str, owner_name: str = "owner") -> list[Fact]:
    """
    Extract and store any facts found in a user utterance.
    High-confidence facts are auto-stored.
    Low-confidence facts are stored as unconfirmed (need user confirmation).
    Returns list of stored facts.
    """
    if not should_extract(text):
        return []

    candidates = extract_facts(text, owner_name=owner_name)
    stored: list[Fact] = []

    for c in candidates:
        fact = get_fact_store().upsert(
            subject    = c.subject,
            predicate  = c.predicate,
            value      = c.value,
            raw_value  = c.raw_value,
            unit       = c.unit,
            confidence = c.confidence,
            confirmed  = not c.needs_confirmation,
            source     = c.source,
        )
        stored.append(fact)

        if c.needs_confirmation:
            log.info(
                "Fact pending confirmation: %s.%s = %s (%.0f%%)",
                c.subject, c.predicate, c.value, c.confidence * 100,
            )

    return stored


def recall_fact(query: str) -> RecallResult:
    """
    Attempt to retrieve a fact from structured or vector memory.
    Returns RecallResult with found=True if retrieved.
    The caller should bypass the LLM when found=True.
    """
    return recall(query)


def get_facts(
    subject:   str = "",
    predicate: str = "",
    category:  str = "",
) -> list[Fact]:
    """Query facts from structured memory."""
    return get_fact_store().search(subject=subject, predicate=predicate, category=category)


def confirm_fact(fact_id: str) -> bool:
    """Mark a pending fact as confirmed by the user."""
    return get_fact_store().confirm(fact_id)


def get_pending_confirmations() -> list[Fact]:
    """Return facts that need user confirmation."""
    all_facts = get_fact_store().get_all(confirmed_only=False)
    return [f for f in all_facts if not f.confirmed and f.confidence < 0.9]


def build_fact_context(query: str, top_k: int = 5) -> str:
    """
    Build a fact context string for injection into Qwen.
    Called by Context Builder to include relevant facts.
    """
    try:
        from app.services.memory.recall_engine import _parse_query
        subject, _ = _parse_query(query.lower())
        if not subject:
            return ""
        facts = get_fact_store().search(subject=subject)
        if not facts:
            return ""
        lines = [f"- {f.display()}" for f in facts[:top_k]]
        return "STORED FACTS:\n" + "\n".join(lines)
    except Exception:
        return ""


def memory_stats() -> dict:
    """Return structured memory statistics."""
    return get_fact_store().stats()

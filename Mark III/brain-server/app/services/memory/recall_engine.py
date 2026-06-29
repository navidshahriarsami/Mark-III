"""
MARK III — Recall Engine

Authoritative fact retrieval. Always checks structured memory first.
The LLM is never consulted for facts that exist in structured memory.

Retrieval order:
  1. Structured Memory (SQLite)  — exact, versioned, authoritative
  2. Vector Memory (ChromaDB)    — semantic, fuzzy
  3. Obsidian Vault              — documentation knowledge
  4. LLM                         — only when retrieval fails completely

This engine is called by query_council() before the LLM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("markiii.memory.recall")


@dataclass
class RecallResult:
    found:      bool
    answer:     str
    source:     str   # "structured" | "vector" | "obsidian" | "none"
    confidence: float
    fact_id:    str   = ""


# ── Query patterns for fact lookup ─────────────────────────────────────────────

_FACT_QUERY_RE = re.compile(
    r"\b(?:what(?:'s| is| was| are))?\s*"
    r"(?:the\s+)?(.+?)'?s?\s+"
    r"(budget|cost|deadline|email|phone|launch|date|status|goal|"
    r"priority|amount|price|password|ip|address|version|id|number|"
    r"preference|ide|tool|language|framework|milestone|revenue|funding)\b",
    re.I,
)

_HOW_MUCH_RE = re.compile(
    r"\bhow\s+much\s+(?:is|does|did|will)?\s*(?:the\s+)?(.+?)\s+"
    r"(?:budget|cost|price|amount|revenue|fund)\b",
    re.I,
)

_WHEN_RE = re.compile(
    r"\bwhen\s+(?:is|does|will|did)?\s*(?:the\s+)?(.+?)\s+"
    r"(?:launch|ship|release|deadline|due|deliver)\b",
    re.I,
)


def recall(query: str) -> RecallResult:
    """
    Main recall entry point.
    Returns RecallResult with found=True and the answer if a fact was retrieved.
    """
    query_lower = query.lower().strip()

    # ── 1. Structured Memory (exact) ──────────────────────────────────────────
    result = _check_structured_memory(query_lower)
    if result.found:
        return result

    # ── 2. Vector Memory (semantic) ───────────────────────────────────────────
    result = _check_vector_memory(query_lower)
    if result.found:
        return result

    return RecallResult(found=False, answer="", source="none", confidence=0.0)


def _check_structured_memory(query: str) -> RecallResult:
    """Query the SQLite fact store with extracted subject + predicate."""
    try:
        from app.services.memory.fact_store import get_fact_store

        store = get_fact_store()
        subject, predicate = _parse_query(query)

        if subject and predicate:
            fact = store.get(subject, predicate)
            if fact:
                val = f"{fact.value} {fact.unit}".strip() if fact.unit else fact.value
                answer = f"{fact.subject} {fact.predicate}: {val}."
                log.info(
                    "Structured recall: %s.%s = %s (conf=%.0f%%)",
                    subject, predicate, val, fact.confidence * 100,
                )
                return RecallResult(
                    found=True, answer=answer, source="structured",
                    confidence=fact.confidence, fact_id=fact.id,
                )

        # Broader search if exact match failed
        if subject:
            facts = store.search(subject=subject)
            if facts:
                lines = [f"{f.predicate}: {f.value} {f.unit}".strip() for f in facts[:3]]
                answer = f"{subject}: " + ", ".join(lines) + "."
                return RecallResult(
                    found=True, answer=answer, source="structured",
                    confidence=0.75, fact_id=facts[0].id,
                )

    except Exception as e:
        log.debug("Structured memory error: %s", e)

    return RecallResult(found=False, answer="", source="none", confidence=0.0)


def _check_vector_memory(query: str) -> RecallResult:
    """Check ChromaDB and SQLite vector memory for semantic matches."""
    try:
        from app.services.memory.chroma_store import get_chroma_store
        results = get_chroma_store().search(query, top_k=1, min_score=0.7)
        if results and results[0].score >= 0.75:
            return RecallResult(
                found=True, answer=results[0].content,
                source="vector", confidence=results[0].score,
            )
    except Exception as e:
        log.debug("Vector memory error: %s", e)

    return RecallResult(found=False, answer="", source="none", confidence=0.0)


def _parse_query(query: str) -> tuple[str, str]:
    """Extract subject and predicate from a query string."""
    # "what is X's budget" / "how much is X budget"
    for pattern in [_FACT_QUERY_RE, _HOW_MUCH_RE, _WHEN_RE]:
        m = pattern.search(query)
        if m:
            subject   = m.group(1).strip().rstrip("'s")
            predicate = m.group(2).strip().lower() if len(m.groups()) >= 2 else ""
            return subject, predicate

    return "", ""


def is_fact_query(text: str) -> bool:
    """Quickly determine if a query is asking for a stored fact."""
    t = text.lower()
    if any(p.search(t) for p in [_FACT_QUERY_RE, _HOW_MUCH_RE, _WHEN_RE]):
        return True
    return False

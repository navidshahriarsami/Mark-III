"""
MARK III — Knowledge Classifier

Classifies every interaction into a knowledge domain.
Drives governance routing decisions.

Domains:
  ENGINEERING   — architecture, ADRs, code decisions, protocols
  USER_FACT     — projects, budgets, deadlines, contacts, preferences
  USER_IDENTITY — profile changes, goal updates, preference shifts
  OPERATIONAL   — diagnostics, mesh health, device status, metrics
  EXPERIENTIAL  — learned patterns, workflows, interaction history
  TEMPORARY     — casual conversation, questions, reasoning outputs
"""
from __future__ import annotations

import re
from enum import Enum


class KnowledgeDomain(str, Enum):
    ENGINEERING   = "engineering"
    USER_FACT     = "user_fact"
    USER_IDENTITY = "user_identity"
    OPERATIONAL   = "operational"
    EXPERIENTIAL  = "experiential"
    TEMPORARY     = "temporary"


class KnowledgeClassification:
    domain:     KnowledgeDomain
    confidence: float
    reason:     str
    permanent:  bool

    def __init__(self, domain: KnowledgeDomain, confidence: float, reason: str) -> None:
        self.domain     = domain
        self.confidence = confidence
        self.reason     = reason
        self.permanent  = domain not in (KnowledgeDomain.TEMPORARY,)


# ── Signal patterns per domain ─────────────────────────────────────────────────

_ENGINEERING_SIGNALS = re.compile(
    r"\b(architecture|adr|api|protocol|subsystem|pipeline|module|service|"
    r"class|function|import|database|schema|endpoint|interface|contract|"
    r"implementation|refactor|design|build|deploy|commit|push|phase|version|"
    r"changelog|roadmap|manifest|document|spec|diagram|mesh|qwen|ollama|"
    r"chromadb|whisper|piper|tailscale)\b",
    re.I,
)

_USER_FACT_SIGNALS = re.compile(
    r"\b(budget|cost|price|amount|deadline|due|launch|client|project|"
    r"email|phone|contact|organisation|company|meeting|task|"
    r"visa|immigration|application|fee|payment|contract)\b",
    re.I,
)

_USER_IDENTITY_SIGNALS = re.compile(
    r"\b(my name|i am|i prefer|i work|i use|my goal|my project|"
    r"my preferred|my deadline|remember that i|i usually|i always)\b",
    re.I,
)

_OPERATIONAL_SIGNALS = re.compile(
    r"\b(temperature|cpu|gpu|ram|disk|network|ping|latency|device|"
    r"battery|status|online|offline|error|crash|log|diagnostic|health|"
    r"uptime|metric|performance|mesh|presence)\b",
    re.I,
)

_EXPERIENTIAL_SIGNALS = re.compile(
    r"\b(pattern|habit|workflow|automation|learned|noticed|tendency|"
    r"usually|often|frequently|always|prefer|style|approach)\b",
    re.I,
)

_FACT_STATEMENT = re.compile(
    r"\b(is|are|was|costs?|has|will be)\b.{0,60}$",
    re.I,
)


def classify(text: str) -> KnowledgeClassification:
    """
    Classify a piece of text into a knowledge domain.
    Uses signal scoring — the domain with most signals wins.
    """
    scores: dict[KnowledgeDomain, float] = {d: 0.0 for d in KnowledgeDomain}

    eng_hits  = len(_ENGINEERING_SIGNALS.findall(text))
    fact_hits = len(_USER_FACT_SIGNALS.findall(text))
    iden_hits = len(_USER_IDENTITY_SIGNALS.findall(text))
    ops_hits  = len(_OPERATIONAL_SIGNALS.findall(text))
    exp_hits  = len(_EXPERIENTIAL_SIGNALS.findall(text))

    scores[KnowledgeDomain.ENGINEERING]   = eng_hits  * 1.5
    scores[KnowledgeDomain.USER_FACT]     = fact_hits * 1.2
    scores[KnowledgeDomain.USER_IDENTITY] = iden_hits * 1.3
    scores[KnowledgeDomain.OPERATIONAL]   = ops_hits  * 1.0
    scores[KnowledgeDomain.EXPERIENTIAL]  = exp_hits  * 0.9

    # Fact statements boost USER_FACT
    if _FACT_STATEMENT.search(text) and fact_hits:
        scores[KnowledgeDomain.USER_FACT] += 2.0

    total = sum(scores.values())
    if total < 0.5:
        return KnowledgeClassification(
            KnowledgeDomain.TEMPORARY, 1.0, "no domain signals",
        )

    winner = max(scores, key=lambda d: scores[d])
    conf   = min(scores[winner] / max(total, 1.0), 1.0)
    return KnowledgeClassification(winner, conf, f"{winner.value} signals={scores[winner]:.1f}")


def is_permanent(text: str) -> bool:
    """True if the text likely contains knowledge that should be persisted."""
    c = classify(text)
    return c.permanent and c.confidence >= 0.4

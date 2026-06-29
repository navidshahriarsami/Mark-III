"""
MARK III — Knowledge Governor

Orchestrator for the Knowledge Governance System.

Every interaction passes through the governor to determine:
  1. What domain does this knowledge belong to?
  2. Is it permanent or temporary?
  3. Where should it be stored?
  4. Does it require repository update?

The governor does not store facts — it routes them to the correct subsystem.

Governance flow:
  Text → Classify → Route → {structured_memory | identity | chroma | repository | discard}
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

log = logging.getLogger("markiii.governance.governor")


@dataclass
class GovernanceDecision:
    domain:     str
    permanent:  bool
    route:      str   # "structured_memory" | "identity" | "vector" | "repository" | "discard"
    confidence: float
    reason:     str


class KnowledgeGovernor:
    """
    Singleton governance orchestrator.
    Started by mark_service alongside the voice loop.
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._start_observer()
        log.info("Knowledge Governance System active")

    def govern(self, text: str) -> GovernanceDecision:
        """
        Classify text and return a routing decision.
        Non-blocking — classification is <1ms.
        """
        try:
            from app.services.governance.knowledge_classifier import classify, KnowledgeDomain
            c = classify(text)

            route_map = {
                KnowledgeDomain.USER_FACT:     "structured_memory",
                KnowledgeDomain.USER_IDENTITY: "identity",
                KnowledgeDomain.ENGINEERING:   "repository",
                KnowledgeDomain.OPERATIONAL:   "vector",
                KnowledgeDomain.EXPERIENTIAL:  "vector",
                KnowledgeDomain.TEMPORARY:     "discard",
            }

            return GovernanceDecision(
                domain     = c.domain.value,
                permanent  = c.permanent,
                route      = route_map.get(c.domain, "discard"),
                confidence = c.confidence,
                reason     = c.reason,
            )
        except Exception as e:
            log.debug("Governance error: %s", e)
            return GovernanceDecision(
                domain="temporary", permanent=False,
                route="discard", confidence=1.0, reason=str(e),
            )

    def run_diagnostics(self) -> dict:
        try:
            from app.services.governance.repository_diagnostics import run_diagnostics
            report = run_diagnostics()
            return {"summary": report.summary, "healthy": report.healthy}
        except Exception as e:
            return {"error": str(e)}

    def _start_observer(self) -> None:
        try:
            from app.services.governance.repository_observer import get_repository_observer
            obs = get_repository_observer()
            obs.start()
        except Exception as e:
            log.debug("Observer start error: %s", e)


# ── Singleton ─────────────────────────────────────────────────────────────────

_governor: KnowledgeGovernor | None = None
_gov_lock  = threading.Lock()


def get_governor() -> KnowledgeGovernor:
    global _governor
    if _governor is None:
        with _gov_lock:
            if _governor is None:
                _governor = KnowledgeGovernor()
    return _governor

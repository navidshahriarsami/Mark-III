"""
MARK III Cognitive Council — Voting Engine

When multiple specialists produce overlapping outputs, the voting engine
decides which responses are worth forwarding to the Executive.

Strategy (no LLM cost):
  1. Filter out errored or empty responses
  2. Score each response on length, keyword relevance, and coherence signals
  3. If a specialist's score is below the threshold, exclude it from Executive context
     (it would just add noise)

This is intentionally lightweight — the Executive does the real synthesis.
Voting only removes clearly bad responses before they pollute the context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SpecialistResponse:
    role:       str
    name:       str
    text:       str
    model:      str
    provider:   str
    latency_ms: float
    cost_usd:   float
    error:      str | None = None
    tokens_in:  int = 0
    tokens_out: int = 0


@dataclass
class VotingResult:
    accepted:        list[SpecialistResponse]
    rejected:        list[SpecialistResponse]
    total_responses: int
    total_accepted:  int
    reasons:         dict[str, str] = field(default_factory=dict)  # role → reason for rejection


# Signals that indicate low-quality / off-topic output
_LOW_QUALITY_PATTERNS = [
    re.compile(r"^(i (cannot|can't|am unable|don't know)|sorry|as an ai)", re.IGNORECASE),
    re.compile(r"i (don't|do not) have (access|information|data)", re.IGNORECASE),
]

_MIN_WORDS = 10


def _score(resp: SpecialistResponse, query: str) -> float:
    """Heuristic quality score 0–1."""
    if resp.error or not resp.text.strip():
        return 0.0

    words = resp.text.split()
    if len(words) < _MIN_WORDS:
        return 0.1

    score = 0.5

    # Low-quality openers → penalise
    for pat in _LOW_QUALITY_PATTERNS:
        if pat.search(resp.text[:120]):
            score -= 0.4

    # Word count bonus (up to +0.3 for 200+ words)
    word_bonus = min(len(words) / 200, 1.0) * 0.3
    score += word_bonus

    # Query term overlap bonus (up to +0.2)
    query_terms = set(re.findall(r'\b\w{4,}\b', query.lower()))
    resp_terms  = set(re.findall(r'\b\w{4,}\b', resp.text.lower()))
    if query_terms:
        overlap = len(query_terms & resp_terms) / len(query_terms)
        score  += overlap * 0.2

    return min(max(score, 0.0), 1.0)


def vote(
    responses: list[SpecialistResponse],
    query:     str,
    threshold: float = 0.2,
) -> VotingResult:
    """
    Filter specialist responses by quality score.
    Responses below `threshold` are rejected before reaching the Executive.
    """
    accepted: list[SpecialistResponse] = []
    rejected: list[SpecialistResponse] = []
    reasons:  dict[str, str]           = {}

    for resp in responses:
        if resp.error:
            rejected.append(resp)
            reasons[resp.role] = f"error: {resp.error}"
            continue

        if not resp.text.strip():
            rejected.append(resp)
            reasons[resp.role] = "empty response"
            continue

        s = _score(resp, query)
        if s >= threshold:
            accepted.append(resp)
        else:
            rejected.append(resp)
            reasons[resp.role] = f"low quality score ({s:.2f})"

    return VotingResult(
        accepted        = accepted,
        rejected        = rejected,
        total_responses = len(responses),
        total_accepted  = len(accepted),
        reasons         = reasons,
    )

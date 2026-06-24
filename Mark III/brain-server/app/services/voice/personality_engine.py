from __future__ import annotations

"""
MARK III Personality Engine — Phase 13.8

Classifies each query by conversational register and builds a per-call
context hint that tells the Executive council the correct humor frequency
and tone.

Humor frequency table:
  serious  →  0 %   (health, legal, financial distress, grief)
  work     → 10 %   (code, meetings, deadlines, tasks)
  casual   → 30 %   (everything else)
"""

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Topic classifiers
# ---------------------------------------------------------------------------

_SERIOUS_KEYWORDS: frozenset[str] = frozenset({
    "health", "medical", "doctor", "hospital", "sick", "cancer",
    "death", "died", "dying", "funeral", "grief", "suicide", "hurt",
    "pain", "injury", "illness", "diagnosed", "prescription",
    "legal", "court", "lawyer", "lawsuit", "arrest", "crime", "police",
    "emergency", "accident", "crash", "fire",
    "bankrupt", "debt", "eviction", "foreclosure", "broke", "loan",
    "divorce", "breakup", "abuse", "assault",
    "depressed", "depression", "anxiety", "panic", "ptsd",
})

_WORK_KEYWORDS: frozenset[str] = frozenset({
    "code", "coding", "debug", "bug", "error", "function", "class",
    "algorithm", "database", "api", "server", "deploy", "git", "commit",
    "meeting", "deadline", "email", "task", "project", "presentation",
    "work", "job", "client", "boss", "office", "report", "proposal",
    "schedule", "calendar", "appointment", "invoice", "sprint", "ticket",
    "build", "compile", "test", "review", "pull", "branch",
})


def classify_topic(query: str) -> str:
    """Return 'serious' | 'work' | 'casual'."""
    tokens = frozenset(re.findall(r"\b\w+\b", query.lower()))
    if tokens & _SERIOUS_KEYWORDS:
        return "serious"
    if tokens & _WORK_KEYWORDS:
        return "work"
    return "casual"


# ---------------------------------------------------------------------------
# Time of day
# ---------------------------------------------------------------------------

def time_of_day() -> str:
    h = datetime.now().hour
    if  5 <= h < 12: return "morning"
    if 12 <= h < 17: return "afternoon"
    if 17 <= h < 22: return "evening"
    return "late night"


# ---------------------------------------------------------------------------
# Humor instruction per topic
# ---------------------------------------------------------------------------

_HUMOR = {
    "serious": (
        "Serious topic — zero humor. Be precise, direct, and grounded."
    ),
    "work": (
        "Work context — 10% humor ceiling. "
        "Sharp and practical first. One dry aside is acceptable if it fits naturally."
    ),
    "casual": (
        "Casual conversation — 30% humor. "
        "A single wry observation is welcome. Keep it dry — not a performance."
    ),
}

# ---------------------------------------------------------------------------
# Context hint builder
# ---------------------------------------------------------------------------

def build_context_hint(query: str) -> str:
    """
    Build a per-query context string for the Executive council.
    Encodes: voice format rules, time, topic type, humor frequency.
    """
    topic = classify_topic(query)
    tod   = time_of_day()
    date  = datetime.now().strftime("%Y-%m-%d")
    humor = _HUMOR[topic]

    return (
        f"Voice delivery. 1–3 sentences. No markdown, no bullet points, no lists.\n"
        f"Current time: {tod}, {date}.\n"
        f"Topic: {topic}. {humor}"
    )

"""
MARK III — Fact Extractor

Detects factual statements in user utterances and extracts structured facts.

Two-stage approach:
  1. Rule-based patterns (fast, <1ms) — handles common fact structures
  2. Qwen-assisted extraction (2-3s) — for complex or ambiguous statements

Pattern examples:
  "The Project Orphans budget is 10 thousand dollars AUD"
  "My visa deadline is March 15"
  "John's email is john@example.com"
  "I prefer Cursor for coding"
  "PathwayAU MVP launches in Q3 2026"
  "The meeting is at 3pm Monday"

Outputs a list of ExtractedFact candidates — not yet stored.
The caller decides whether to auto-store or ask for confirmation.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.memory.fact_normalizer import normalize, NormalizedValue

log = logging.getLogger("markiii.memory.extractor")


@dataclass
class ExtractedFact:
    subject:    str
    predicate:  str
    value:      str
    unit:       str
    raw_value:  str
    confidence: float      # 0.0-1.0
    source:     str        # "rule" | "qwen"
    needs_confirmation: bool = False


# ── Predicate vocabulary ───────────────────────────────────────────────────────

_BUDGET_WORDS    = r"(?:budget|cost|price|amount|funding|revenue|spend|expense)"
_DEADLINE_WORDS  = r"(?:deadline|due|launch|release|delivery|target date|ships?)"
_GOAL_WORDS      = r"(?:goal|objective|milestone|target|aim)"
_PREF_WORDS      = r"(?:prefer|use|like|favourite|favorite|default|primary)"
_STATUS_WORDS    = r"(?:status|state|stage|phase|progress)"

# ── Extraction patterns ────────────────────────────────────────────────────────
# Each pattern: (regex, subject_group, predicate, predicate_label, confidence)

_PATTERNS: list[tuple] = [

    # "The [Project X] budget is [VALUE]"
    (
        re.compile(
            r"(?:the\s+)?(.+?)\s+" + _BUDGET_WORDS + r"\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, "budget", 0.90,
    ),

    # "[Project X]'s budget is [VALUE]"
    (
        re.compile(
            r"(.+?)'?s?\s+" + _BUDGET_WORDS + r"\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, "budget", 0.90,
    ),

    # "[Project X] deadline is [DATE]"
    (
        re.compile(
            r"(?:the\s+)?(.+?)\s+" + _DEADLINE_WORDS + r"\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, "deadline", 0.85,
    ),

    # "I prefer [VALUE] for [SUBJECT]" / "my preferred [SUBJECT] is [VALUE]"
    (
        re.compile(
            r"(?:I\s+)?" + _PREF_WORDS + r"\s+(.+?)\s+for\s+(.+?)(?:\.|$)",
            re.I
        ),
        2, 1, "preferred_tool", 0.80,
    ),

    # "[X] email is [EMAIL]" / "[X]'s email is [EMAIL]"
    (
        re.compile(
            r"(.+?)'?s?\s+(?:email|email address|contact)\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, "email", 0.92,
    ),

    # "My [PREDICATE] is [VALUE]" — generic personal fact
    (
        re.compile(
            r"my\s+(.+?)\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        None, 1, None, 0.75,  # subject="owner", predicate=group1, value=group2
    ),

    # "[X] launches in [DATE]" / "[X] is launching in [DATE]"
    (
        re.compile(
            r"(.+?)\s+(?:launches?|is launching|ships?|goes live)\s+(?:in|on)?\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, "launch_date", 0.80,
    ),

    # "[X]'s [PREDICATE] is [VALUE]" — generic entity fact
    (
        re.compile(
            r"(.+?)'s?\s+(\w+)\s+is\s+(.+?)(?:\.|$)",
            re.I
        ),
        1, 2, None, 0.70,  # predicate=group2, value=group3
    ),
]

# Common noise words that indicate the utterance is NOT a fact statement
_NON_FACT_INDICATORS = re.compile(
    r"\b(what|how|why|when|where|who|can you|could you|would you|should i|"
    r"tell me|explain|help me|do you|are you|is it|does it)\b",
    re.I,
)

# Indicators that this IS likely a fact statement
_FACT_INDICATORS = re.compile(
    r"\b(is|are|was|will be|costs?|budget|deadline|email|phone|"
    r"prefer|use|launch|ships?|amount|price|date)\b",
    re.I,
)


def extract_facts(text: str, owner_name: str = "owner") -> list[ExtractedFact]:
    """
    Extract all factual statements from a user utterance.
    Returns a list of candidates (not yet stored).
    """
    facts: list[ExtractedFact] = []

    # Quick filter: skip clearly non-factual queries
    if _NON_FACT_INDICATORS.match(text.strip()):
        return facts
    if not _FACT_INDICATORS.search(text):
        return facts

    # Try each pattern
    for pattern, subj_grp, val_grp, predicate_label, base_confidence in _PATTERNS:
        for match in pattern.finditer(text):
            try:
                groups = match.groups()

                # Extract subject
                if subj_grp is None:
                    subject = owner_name
                else:
                    subject = groups[subj_grp - 1].strip().rstrip("'s")

                # Extract predicate
                if predicate_label:
                    predicate = predicate_label
                elif val_grp and len(groups) >= 3:
                    predicate = groups[1].strip().lower().replace(" ", "_")
                else:
                    continue

                # Extract value
                raw_value = groups[val_grp - 1].strip() if val_grp else ""
                if not raw_value or len(raw_value) < 1:
                    continue

                # Normalize
                norm: NormalizedValue = normalize(raw_value)

                # Skip if subject or value looks like noise
                if len(subject) < 2 or len(norm.value) < 1:
                    continue

                facts.append(ExtractedFact(
                    subject    = subject,
                    predicate  = predicate,
                    value      = norm.value,
                    unit       = norm.unit,
                    raw_value  = raw_value,
                    confidence = base_confidence,
                    source     = "rule",
                    needs_confirmation = base_confidence < 0.85,
                ))
                log.debug(
                    "Extracted: %s.%s = %s %s (conf=%.0f%%)",
                    subject, predicate, norm.value, norm.unit, base_confidence * 100,
                )

            except (IndexError, AttributeError):
                continue

    # Deduplicate by (subject, predicate)
    seen = set()
    unique = []
    for f in facts:
        key = (f.subject.lower(), f.predicate.lower())
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique


def should_extract(text: str) -> bool:
    """Quick check: does this utterance likely contain a fact worth extracting?"""
    if len(text.split()) < 4:
        return False
    if _NON_FACT_INDICATORS.match(text.strip()):
        return False
    return bool(_FACT_INDICATORS.search(text))

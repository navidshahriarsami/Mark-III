"""
MARK III Reflex — Calendar Module

Stub — Google Calendar / Outlook integration planned.
"""
from __future__ import annotations
import re
from typing import Optional

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(my |today'?s |upcoming )?(schedule|calendar|events?|meetings?|appointments?)\b", re.I), "schedule"),
    (re.compile(r"\bdo i have (anything|something) (today|tomorrow|this week)\b",                     re.I), "schedule"),
    (re.compile(r"\bwhat'?s (on my calendar|my schedule)\b",                                          re.I), "schedule"),
    (re.compile(r"\b(my |any )?(reminders?|deadlines?)\b",                                            re.I), "reminders"),
]


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            return "Calendar integration not yet connected. Add Google or Outlook calendar to enable this."
    return None

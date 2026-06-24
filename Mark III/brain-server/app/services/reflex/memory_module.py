"""
MARK III Reflex — Memory Module

Handles recall of goals, projects, reminders stored in MARK's memory files.
Reads from brain-server/memory/ directory.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "memory")

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bwhat('?s| are) my (current )?(goals?|projects?|tasks?)\b|\bmy goals?\b", re.I), "goals"),
    (re.compile(r"\bdo i have (any )?reminders?\b|\bany (upcoming )?reminders?\b",            re.I), "reminders"),
    (re.compile(r"\bwhat (was i|am i) working on\b|\bmy (current )?project\b",                re.I), "projects"),
    (re.compile(r"\bremember when\b|\bwhat did (you|mark) remember\b|\bwhat do you know about me\b", re.I), "recall"),
]


def can_handle(text: str) -> bool:
    return any(p.search(text) for p, _ in _PATTERNS)


def handle(text: str) -> Optional[str]:
    for pattern, action in _PATTERNS:
        if pattern.search(text):
            fn = globals().get(f"_get_{action}")
            if fn:
                return fn()
    return None


def _load_memory_file(name: str) -> Optional[dict]:
    path = os.path.join(_MEMORY_DIR, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Strip YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        return {"text": content}
    except Exception:
        return None


def _get_goals() -> str:
    return "Goal tracking not yet set up. Add goals to MARK's memory system to recall them here."


def _get_reminders() -> str:
    return "No active reminders stored. Use MARK's memory to set reminders."


def _get_projects() -> str:
    d = _load_memory_file("project_markiii.md")
    if d:
        lines = [l.strip() for l in d["text"].splitlines() if l.strip() and not l.startswith("#")][:3]
        if lines:
            return "Current project: " + lines[0]
    return "No project data found in memory."


def _get_recall() -> str:
    return "I remember your profile and our project history, but I need more context. What specifically do you want me to recall?"

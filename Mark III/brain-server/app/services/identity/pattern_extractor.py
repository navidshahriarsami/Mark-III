"""
MARK III — Pattern Extractor

Extracts structured patterns from session summaries and conversation data.
Runs after each session summarization.

Extraction categories:
  preferences    — response style, depth, tone preferences
  workflows      — repeated task sequences
  decisions      — engineering or personal decisions made
  interests      — topics that recur across sessions
  tools          — apps, IDEs, languages frequently mentioned
  schedule       — inferred working hours and routines

Two-stage approach:
  1. Rule-based fast extraction (regex, keyword matching) — always runs
  2. Qwen-assisted extraction — runs for complex/long summaries

Only patterns with repeat signals become permanent preferences.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("markiii.identity.patterns")


@dataclass
class ExtractedPattern:
    category:    str          # "preference" | "workflow" | "interest" | "tool" | "schedule"
    key:         str          # machine-readable identifier
    value:       str          # human-readable description
    confidence:  float        # 0.0-1.0
    source:      str          # "rule" | "qwen"


# ─── Rule-based extractors ────────────────────────────────────────────────────

_TOOL_RE = re.compile(
    r"\b(VS Code|vscode|PyCharm|Xcode|cursor|neovim|vim|"
    r"Chrome|Firefox|Safari|Edge|"
    r"GitHub|GitLab|Notion|Obsidian|Figma|Slack|Discord|"
    r"Python|Swift|JavaScript|TypeScript|Go|Rust|Java)\b",
    re.I,
)

_SCHEDULE_RE = re.compile(
    r"\b(morning|evening|afternoon|night|after \d+|before \d+|"
    r"\d+\s*[ap]m|working hours|focus time|standup|end of day)\b",
    re.I,
)

_PREF_CONCISE = re.compile(r"\b(brief|concise|short|quick|summarise|tldr|keep it short)\b", re.I)
_PREF_DETAIL  = re.compile(r"\b(detailed|thorough|in[- ]depth|explain|elaborate|more detail)\b", re.I)
_PREF_TECH    = re.compile(r"\b(technical|implementation|architecture|codebase|engineering)\b", re.I)


def extract_from_text(text: str) -> list[ExtractedPattern]:
    """
    Fast rule-based pattern extraction from any text.
    Used on session summaries, conversation turns, and user messages.
    """
    patterns: list[ExtractedPattern] = []

    # Tool/app mentions
    tools = list(set(m.group() for m in _TOOL_RE.finditer(text)))
    for tool in tools:
        patterns.append(ExtractedPattern(
            category="tool", key=f"tool_{tool.lower().replace(' ', '_')}",
            value=f"Uses {tool}", confidence=0.5, source="rule",
        ))

    # Schedule signals
    schedule = list(set(m.group() for m in _SCHEDULE_RE.finditer(text)))
    if schedule:
        patterns.append(ExtractedPattern(
            category="schedule", key="schedule_signal",
            value=f"Schedule context: {', '.join(schedule[:3])}",
            confidence=0.4, source="rule",
        ))

    # Response preference signals
    if _PREF_CONCISE.search(text):
        patterns.append(ExtractedPattern(
            category="preference", key="response_length",
            value="Prefers concise responses", confidence=0.6, source="rule",
        ))
    if _PREF_DETAIL.search(text):
        patterns.append(ExtractedPattern(
            category="preference", key="response_depth",
            value="Prefers detailed explanations", confidence=0.6, source="rule",
        ))
    if _PREF_TECH.search(text):
        patterns.append(ExtractedPattern(
            category="preference", key="technical_focus",
            value="Frequently discusses technical topics", confidence=0.7, source="rule",
        ))

    return patterns


def extract_from_summary(summary: str, use_qwen: bool = False) -> list[ExtractedPattern]:
    """
    Extract patterns from a session summary.
    Optionally uses Qwen for richer extraction on long summaries.
    """
    patterns = extract_from_text(summary)

    if use_qwen and len(summary.split()) > 50:
        try:
            qwen_patterns = _qwen_extract(summary)
            patterns.extend(qwen_patterns)
        except Exception as e:
            log.debug("Qwen extraction failed: %s", e)

    return patterns


def _qwen_extract(summary: str) -> list[ExtractedPattern]:
    """Use Qwen to extract structured patterns from a session summary."""
    import httpx
    prompt = (
        "Extract behavioral patterns from this session summary. "
        "List only concrete, specific patterns (tools used, preferences shown, decisions made). "
        "Format: one pattern per line as 'category: description'\n\n"
        f"Summary:\n{summary[:800]}\n\nPatterns:"
    )
    r = httpx.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen2.5:7b",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 150, "temperature": 0.1},
        },
        timeout=15.0,
    )
    if r.status_code != 200:
        return []

    lines = r.json().get("message", {}).get("content", "").strip().split("\n")
    patterns = []
    for line in lines:
        if ":" in line:
            cat, _, desc = line.partition(":")
            cat  = cat.strip().lower()
            desc = desc.strip()
            if cat and desc and len(desc) > 5:
                patterns.append(ExtractedPattern(
                    category=cat, key=f"qwen_{cat}_{len(desc)}",
                    value=desc, confidence=0.65, source="qwen",
                ))
    return patterns


def apply_patterns_to_profile(patterns: list[ExtractedPattern]) -> None:
    """Store high-confidence patterns in vector memory and update profile."""
    if not patterns:
        return

    try:
        from app.services.memory.chroma_store import get_chroma_store
        from app.services.identity.identity_manager import get_identity_manager
        from datetime import datetime

        chroma = get_chroma_store()
        mgr    = get_identity_manager()

        for p in patterns:
            if p.confidence < 0.5:
                continue
            doc_id = f"pattern_{p.key}_{datetime.now().strftime('%Y%m%d')}"
            chroma.add(
                content    = p.value,
                doc_id     = doc_id,
                collection = "user_prefs",
                metadata   = {
                    "category":   p.category,
                    "key":        p.key,
                    "confidence": str(p.confidence),
                    "source":     p.source,
                },
            )

            # Update preferred_apps directly if a tool pattern is strong
            if p.category == "tool" and p.confidence >= 0.7:
                tool_name = p.value.replace("Uses ", "").strip()
                prefs = mgr.profile.preferred_apps
                if tool_name not in prefs:
                    mgr.update(preferred_apps=[tool_name] + prefs[:9])

    except Exception as e:
        log.debug("Pattern apply error: %s", e)

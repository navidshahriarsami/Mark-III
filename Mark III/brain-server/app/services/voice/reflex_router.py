"""
MARK III Phase 15A — Reflex Router

Intercepts common phrases before any LLM call.
Returns a pre-written response from a local lookup table.

Target latency: <1 ms (dominated by TTS, not this module).

Usage:
    from app.services.voice.reflex_router import match as reflex_match
    answer = reflex_match("are you there")  # "Yes. Listening." or None
"""
from __future__ import annotations

import re
from typing import Optional


# Each entry: (compiled pattern, [candidate responses])
# Responses are chosen deterministically by hash(text) % len so MARK
# doesn't repeat the same phrase every time.
_REFLEX: list[tuple[re.Pattern, list[str]]] = [

    # ── Status checks ──────────────────────────────────────────────────
    (re.compile(
        r"\b(are you there|you there|mark you there|hello there|are you on|"
        r"is anyone there|can you hear me)\b",
        re.I,
    ), [
        "Yes. Listening.",
        "Here.",
        "Online.",
    ]),

    # ── Wake word — single or repeated ("Mark. Mark.") ───────────────
    (re.compile(r"^(mark[\s!?.,]*){1,3}$", re.I), [
        "Yes?",
        "Here.",
        "Go ahead.",
    ]),

    # Time/date patterns removed — now handled by system_module.py (returns live clock)

    # ── Simple greetings ──────────────────────────────────────────────
    (re.compile(r"^(hi|hello|hey|yo)\b[\s!?.]*$", re.I), [
        "Hello.",
        "Hi.",
        "Here.",
    ]),

    # ── How are you ───────────────────────────────────────────────────
    (re.compile(
        r"\bhow are you\b|how('re| are) you doing\b|\bare you okay\b|\bare you well\b",
        re.I,
    ), [
        "Operational.",
        "Systems nominal.",
        "Running well.",
    ]),

    # ── Thanks ────────────────────────────────────────────────────────
    (re.compile(
        r"\b(thanks|thank you|cheers|much appreciated|appreciate it|thank you so much)\b",
        re.I,
    ), [
        "You're welcome.",
        "Of course.",
        "Anytime.",
    ]),

    # ── Affirmative ───────────────────────────────────────────────────
    (re.compile(
        r"^(yes|yeah|yep|yup|correct|right|exactly|sure|affirmative|"
        r"absolutely|indeed|certainly|of course|go ahead)[\s!?.]*$",
        re.I,
    ), [
        "Understood.",
        "Got it.",
        "Confirmed.",
    ]),

    # ── Negative ──────────────────────────────────────────────────────
    (re.compile(
        r"^(no|nope|nah|negative|never mind|nevermind|not now|cancel that)[\s!?.]*$",
        re.I,
    ), [
        "Understood.",
        "Noted.",
    ]),

    # ── Acknowledgment ────────────────────────────────────────────────
    (re.compile(
        r"^(okay|ok|alright|got it|i see|understood|copy|roger|noted|"
        r"makes sense|good to know|i understand|i know)[\s!?.]*$",
        re.I,
    ), [
        "Good.",
        "Noted.",
    ]),

    # ── Farewell ──────────────────────────────────────────────────────
    (re.compile(
        r"^(bye|goodbye|see you|later|good night|goodnight|"
        r"that's all|that is all|signing off|see you later|talk later)[\s!?.]*$",
        re.I,
    ), [
        "Goodbye.",
        "Standing by.",
        "Until next time.",
    ]),

    # ── Work acknowledgments ──────────────────────────────────────────
    (re.compile(
        r"^i (work|am working|started working|finished|am done|completed|"
        r"just finished|just completed|just started)[\s!?.]*$",
        re.I,
    ), [
        "Understood. What do you need?",
        "Noted. How can I assist?",
    ]),

    # ── Wait / hold on ────────────────────────────────────────────────
    (re.compile(
        r"^(wait|hold on|one moment|one sec|just a second|give me a second|"
        r"one minute|give me a minute)[\s!?.]*$",
        re.I,
    ), [
        "Standing by.",
        "Take your time.",
    ]),
]


def match(text: str) -> Optional[str]:
    """
    Check text against all reflex patterns.
    Returns a pre-written response, or None if LLM processing is needed.

    Selection is deterministic: hash(normalized text) % len(responses)
    produces the same response for the same input phrase.
    """
    t = text.strip().rstrip(".!?,; ").strip()
    if not t or len(t.split()) > 8:
        # Reflex only fires on short phrases (≤ 8 words)
        return None

    for pattern, responses in _REFLEX:
        if pattern.search(t):
            return responses[hash(t.lower()) % len(responses)]

    return None

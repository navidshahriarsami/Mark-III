"""
MARK III — Action Router (Phase 12B)

Pure keyword/regex classifier.  No LLM.  No I/O.

Takes a text string (LLM suggestion, voice transcript, API call) and
returns an ActionRequest if an intent is detected, or None if the text
is conversational with no actionable intent.

Design rules:
  - Deterministic: same input → same output, always
  - Fast: called on every conversation turn, must complete in <1ms
  - Conservative: prefer None over a wrong classification
  - Extensible: add patterns to PATTERNS list to cover new intents

LLMs suggest.  The Router decides.  Executors act.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.services.actions.base_action import ActionRequest, ActionType


# ---------------------------------------------------------------------------
# Pattern record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntentPattern:
    action_type: str
    patterns:    tuple[re.Pattern, ...]
    extract:     Optional[str] = None   # named group to extract main param


# ---------------------------------------------------------------------------
# Helper for building patterns
# ---------------------------------------------------------------------------

def _p(*exprs: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(e, re.IGNORECASE) for e in exprs)


# ---------------------------------------------------------------------------
# Pattern table — ordered from most to least specific
#
# Each pattern is matched against the FULL input text.
# First match wins across ALL patterns.
# ---------------------------------------------------------------------------

PATTERNS: list[IntentPattern] = [

    # ── Web (must come before launch_app — 'open URL' would otherwise match launch_app) ──
    IntentPattern(
        ActionType.OPEN_URL,
        _p(
            r"\bopen\s+(?P<url>https?://[^\s]+)",
            r"\bgo\s+to\s+(?P<url>https?://[^\s]+)",
            r"\bnavigate\s+to\s+(?P<url>https?://[^\s]+)",
            r"\bvisit\s+(?P<url>https?://[^\s]+)",
            r"\bopen\s+(?P<url>(?:www\.)[^\s]{3,})",
        ),
        extract="url",
    ),

    # ── Shell commands (must come before launch_app — 'run command:' matches 'run X') ──
    IntentPattern(
        ActionType.RUN_COMMAND,
        _p(
            r"\brun\s+(?:command|shell|terminal|cmd|powershell)[:\s]+(?P<command>.+)",
            r"\bexecute\s+(?:command[:\s]+)?(?P<command>.+)",
            r"\b(?:bash|cmd|powershell)\s*:\s*(?P<command>.+)",
        ),
        extract="command",
    ),

    # ── App control ────────────────────────────────────────────────────────
    IntentPattern(
        ActionType.LAUNCH_APP,
        _p(
            r"\bopen\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40}?)(?:\s+(?:app|application|program|for me))?\b",
            r"\blaunch\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bstart\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\brun\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
        ),
        extract="app_name",
    ),
    IntentPattern(
        ActionType.CLOSE_APP,
        _p(
            r"\bclose\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bquit\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bexit\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bkill\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
        ),
        extract="app_name",
    ),
    IntentPattern(
        ActionType.FOCUS_APP,
        _p(
            r"\bswitch\s+to\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bbring\s+up\s+(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
            r"\bfocus\s+(?:on\s+)?(?P<app_name>[A-Za-z0-9 ._-]{2,40})",
        ),
        extract="app_name",
    ),

    # ── Web search ────────────────────────────────────────────────────────────
    IntentPattern(
        ActionType.WEB_SEARCH,
        _p(
            r"\bsearch\s+(?:the\s+web|online|google|internet)?\s+(?:for\s+)?(?P<query>.+)",
            r"\blook\s+up\s+(?P<query>.+)",
            r"\bgoogle\s+(?P<query>.+)",
            r"\bfind\s+(?:online|on\s+the\s+web)\s+(?P<query>.+)",
        ),
        extract="query",
    ),

    # ── Files (read-only) ────────────────────────────────────────────────────
    IntentPattern(
        ActionType.SEARCH_FILES,
        _p(
            r"\bfind\s+(?:files?|folders?|documents?)\s+(?:named?\s+|called\s+)?(?P<pattern>[^\s].{0,60})",
            r"\bsearch\s+(?:my\s+)?(?:files?|computer|disk|drive)\s+for\s+(?P<pattern>.+)",
            r"\bwhere\s+is\s+(?:my\s+)?(?P<pattern>.+?)(?:\s+file|\s+document|\s+folder)?\?",
            r"\blocate\s+(?P<pattern>.+)",
            r"\bsearch\s+(?:for\s+)?(?P<pattern>\S+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|py|js|ts|json|md|png|jpg|mp4|zip|log))\b",
        ),
        extract="pattern",
    ),
    IntentPattern(
        ActionType.READ_FILE,
        _p(
            r"\bread\s+(?P<path>(?:[A-Za-z]:\\|/)[^\s].{0,200})",
            r"\bshow\s+(?:me\s+)?(?:the\s+)?(?:contents?\s+of\s+)?(?P<path>(?:[A-Za-z]:\\|/)[^\s].{0,200})",
            r"\bcat\s+(?P<path>(?:[A-Za-z]:\\|/)[^\s].{0,200})",
        ),
        extract="path",
    ),
    IntentPattern(
        ActionType.OPEN_FILE,
        _p(
            r"\bopen\s+(?:file\s+)?(?P<path>(?:[A-Za-z]:\\|/)[^\s].{0,200})",
            r"\bopen\s+(?P<path>[^\s]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|md|png|jpg|mp4|mp3))\b",
        ),
        extract="path",
    ),

    # ── File mutations (caution) ──────────────────────────────────────────────
    IntentPattern(
        ActionType.CREATE_FOLDER,
        _p(
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?(?:at\s+)?(?P<path>[^\s].{0,200})",
            r"\bmake\s+(?:a\s+)?(?:new\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?(?P<path>[^\s].{0,200})",
            r"\bmkdir\s+(?P<path>[^\s].{0,200})",
        ),
        extract="path",
    ),
    IntentPattern(
        ActionType.CREATE_FILE,
        _p(
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?file\s+(?:at\s+|called\s+|named\s+)?(?P<path>[^\s].{0,200})",
            r"\btouch\s+(?P<path>[^\s].{0,200})",
        ),
        extract="path",
    ),
    IntentPattern(
        ActionType.COPY_FILE,
        _p(
            r"\bcopy\s+(?P<src>[^\s].{0,200})\s+(?:to|into)\s+(?P<dst>[^\s].{0,200})",
        ),
    ),
    IntentPattern(
        ActionType.MOVE_FILE,
        _p(
            r"\bmove\s+(?P<src>[^\s].{0,200})\s+(?:to|into)\s+(?P<dst>[^\s].{0,200})",
        ),
    ),

    # ── Notifications ─────────────────────────────────────────────────────────
    IntentPattern(
        ActionType.SEND_NOTIFICATION,
        _p(
            r"\bsend\s+(?:me\s+)?(?:a\s+)?(?:notification|alert|reminder)\s+(?:saying\s+|that\s+)?(?P<body>.+)",
            r"\bremind\s+me\s+(?:to\s+)?(?P<body>.+)",
            r"\bnotify\s+me\s+(?:about\s+|when\s+)?(?P<body>.+)",
        ),
        extract="body",
    ),

    # ── Dangerous ─────────────────────────────────────────────────────────────
    IntentPattern(
        ActionType.DELETE_FILE,
        _p(
            r"\bdelete\s+(?P<path>[^\s].{0,200})",
            r"\bremove\s+(?:file\s+|folder\s+)?(?P<path>(?:[A-Za-z]:\\|/)[^\s].{0,200})",
            r"\btrash\s+(?P<path>[^\s].{0,200})",
            r"\brm\s+(?P<path>[^\s].{0,200})",
        ),
        extract="path",
    ),
    IntentPattern(
        ActionType.RENAME_FILE,
        _p(
            r"\brename\s+(?P<path>[^\s].{0,200})\s+(?:to\s+)?(?P<new_name>[^\s].{0,200})",
        ),
    ),
    IntentPattern(
        ActionType.INSTALL_SOFTWARE,
        _p(
            r"\binstall\s+(?P<package>[A-Za-z0-9_\-\.]{1,60})",
            r"\bpip\s+install\s+(?P<package>[A-Za-z0-9_\-\.]{1,60})",
            r"\bnpm\s+install\s+(?P<package>[A-Za-z0-9_\-\.@/]{1,60})",
            r"\bwinget\s+install\s+(?P<package>[A-Za-z0-9_\-\.]{1,60})",
        ),
        extract="package",
    ),
    IntentPattern(
        ActionType.KILL_PROCESS,
        _p(
            r"\bkill\s+process\s+(?P<target>[A-Za-z0-9_\-\.]{1,40})",
            r"\bkill\s+pid\s+(?P<target>\d+)",
            r"\bterminate\s+(?P<target>[A-Za-z0-9_\-\.]{1,40})",
        ),
        extract="target",
    ),

    # ── Critical ──────────────────────────────────────────────────────────────
    IntentPattern(
        ActionType.SYSTEM_SHUTDOWN,
        _p(
            r"\bshutdown\b.*\b(?:computer|pc|system|machine)\b",
            r"\bturn\s+off\b.*\b(?:computer|pc|system|machine)\b",
            r"\bpower\s+off\b",
        ),
    ),
    IntentPattern(
        ActionType.SYSTEM_RESTART,
        _p(
            r"\brestart\b.*\b(?:computer|pc|system|machine)\b",
            r"\breboot\b",
        ),
    ),
]


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

# Words that shouldn't be treated as app names
_APP_STOP_WORDS = frozenset({
    "a", "an", "the", "my", "your", "please", "can", "you", "could", "should",
    "me", "this", "that", "it", "in", "on", "at", "to", "for", "with", "by",
    "app", "application", "program", "software", "file",
})

def _clean_app_name(name: str) -> str:
    words = [w for w in name.strip().split() if w.lower() not in _APP_STOP_WORDS]
    return " ".join(words).strip().rstrip(".,?!")


def _clean_query(q: str) -> str:
    return q.strip().rstrip(".,?!")


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_intent(
    text:       str,
    device_id:  str,
    source:     str                = "conversation",
    session_id: Optional[str]     = None,
) -> Optional[ActionRequest]:
    """
    Match text against PATTERNS.  Return ActionRequest or None.

    Called on every conversation turn and every voice transcript.
    Must complete in < 1ms for hot path.
    """
    if not text or len(text) < 4:
        return None

    for intent in PATTERNS:
        for pattern in intent.patterns:
            m = pattern.search(text)
            if m is None:
                continue

            params = _extract_params(intent.action_type, m, intent.extract)
            if params is None:
                continue

            return ActionRequest(
                action_type  = intent.action_type,
                parameters   = params,
                source       = source,
                device_id    = device_id,
                session_id   = session_id,
                context_hint = text[:200],
            )

    return None


def _extract_params(
    action_type: str,
    match:       re.Match,
    extract:     Optional[str],
) -> Optional[dict]:
    """Build parameters dict from regex match groups."""
    groups = match.groupdict()

    # --- Actions with two capture groups ---
    if action_type in (ActionType.COPY_FILE, ActionType.MOVE_FILE):
        src = groups.get("src", "").strip()
        dst = groups.get("dst", "").strip()
        if not src or not dst:
            return None
        return {"src": src, "dst": dst}

    if action_type == ActionType.RENAME_FILE:
        path     = groups.get("path", "").strip()
        new_name = groups.get("new_name", "").strip()
        if not path or not new_name:
            return None
        return {"path": path, "new_name": new_name}

    # --- Single-value extractions ---
    if extract:
        value = groups.get(extract, "").strip()
        if not value:
            return None

        if action_type == ActionType.LAUNCH_APP:
            value = _clean_app_name(value)
            if len(value) < 2:
                return None
            return {"app_name": value}

        if action_type == ActionType.CLOSE_APP:
            value = _clean_app_name(value)
            if len(value) < 2:
                return None
            return {"app_name": value}

        if action_type == ActionType.FOCUS_APP:
            return {"app_name": _clean_app_name(value)}

        if action_type == ActionType.OPEN_URL:
            url = value.rstrip(".,?!")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return {"url": url}

        if action_type == ActionType.WEB_SEARCH:
            return {"query": _clean_query(value)}

        if action_type == ActionType.SEARCH_FILES:
            return {"pattern": _clean_query(value)}

        if action_type == ActionType.SEND_NOTIFICATION:
            body = _clean_query(value)
            # Derive a short title from body
            title = " ".join(body.split()[:5])
            return {"title": "MARK III", "body": body}

        # Generic single param
        return {extract: _clean_query(value)}

    # No extract — no params needed (e.g., system_shutdown)
    return {}


# ---------------------------------------------------------------------------
# Batch classify (for scanning full LLM response)
# ---------------------------------------------------------------------------

def classify_all(
    text:       str,
    device_id:  str,
    source:     str            = "conversation",
    session_id: Optional[str] = None,
) -> list[ActionRequest]:
    """
    Find ALL distinct intents in a multi-sentence text.

    Used when the LLM response embeds multiple suggestions,
    e.g., "I can open VS Code and search for that file."
    Returns deduplicated action types.
    """
    found:    list[ActionRequest] = []
    seen:     set[str]            = set()
    # Split on sentence boundaries for better matching per-sentence
    sentences = re.split(r"[.!?]+", text)
    for sentence in sentences:
        req = classify_intent(sentence.strip(), device_id, source, session_id)
        if req and req.action_type not in seen:
            found.append(req)
            seen.add(req.action_type)
    return found

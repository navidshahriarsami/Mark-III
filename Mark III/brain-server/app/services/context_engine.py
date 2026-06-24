"""
MARK III Cognitive Engine — Context Derivation

Analyses recent window snapshots to infer the user's current task,
productivity state, confidence score, and suggested action.

No LLM required — pure rule-based signal fusion:
  - Application classifications in a recency-weighted 15-minute window
  - Combination rules (ide + terminal = software_development with high confidence)
  - Time-of-day / work-block awareness
  - Domain signals for career-development detection
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("markiii.cognitive.context")

WINDOW_SECONDS = 900          # 15-minute sliding window
RECENCY_DECAY  = 0.08         # weight = 1 / (1 + index * RECENCY_DECAY)


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class ProductivityState(str, Enum):
    SOFTWARE_DEVELOPMENT = "software_development"
    CAREER_DEVELOPMENT   = "career_development"
    RESEARCH             = "research"
    COMMUNICATION        = "communication"
    ADMINISTRATIVE       = "administrative"
    DISTRACTION          = "distraction"
    ENTERTAINMENT        = "entertainment"
    BREAK                = "break"
    IDLE                 = "idle"
    UNKNOWN              = "unknown"


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class Context:
    current_task:            str
    productivity_state:      ProductivityState
    confidence:              float          # 0.0 – 1.0
    suggested_action:        str
    dominant_app:            str
    dominant_classification: str
    window_count:            int
    is_work_block:           bool


# ---------------------------------------------------------------------------
# Rule tables
# ---------------------------------------------------------------------------

# Single dominant classification → baseline state
_SINGLE_MAP: dict[str, ProductivityState] = {
    "ide":           ProductivityState.SOFTWARE_DEVELOPMENT,
    "terminal":      ProductivityState.SOFTWARE_DEVELOPMENT,
    "communication": ProductivityState.COMMUNICATION,
    "productivity":  ProductivityState.ADMINISTRATIVE,
    "media":         ProductivityState.ENTERTAINMENT,
    "distraction":   ProductivityState.DISTRACTION,
    "browser":       ProductivityState.RESEARCH,
    "system":        ProductivityState.IDLE,
    "unknown":       ProductivityState.UNKNOWN,
}

# Combination rules — most specific match wins (checked in order)
_COMBO_RULES: list[tuple[frozenset, ProductivityState, float]] = [
    (frozenset({"ide", "terminal", "browser"}), ProductivityState.SOFTWARE_DEVELOPMENT, 0.95),
    (frozenset({"ide", "terminal"}),            ProductivityState.SOFTWARE_DEVELOPMENT, 0.92),
    (frozenset({"ide", "browser"}),             ProductivityState.SOFTWARE_DEVELOPMENT, 0.82),
    (frozenset({"terminal", "browser"}),        ProductivityState.SOFTWARE_DEVELOPMENT, 0.72),
    (frozenset({"distraction", "media"}),       ProductivityState.ENTERTAINMENT,        0.90),
    (frozenset({"distraction", "browser"}),     ProductivityState.DISTRACTION,          0.90),
    (frozenset({"communication", "browser"}),   ProductivityState.COMMUNICATION,        0.75),
    (frozenset({"communication", "productivity"}), ProductivityState.COMMUNICATION,     0.78),
    (frozenset({"productivity", "browser"}),    ProductivityState.ADMINISTRATIVE,       0.70),
]

# Browser domain keywords → career development override
_CAREER_KEYWORDS = {
    "linkedin", "indeed", "seek", "glassdoor", "jobs", "careers",
    "resume", "cv", "recruitment", "hiring", "jobactive",
}

# Human-readable labels
_TASK_LABELS: dict[ProductivityState, str] = {
    ProductivityState.SOFTWARE_DEVELOPMENT: "Software Development",
    ProductivityState.CAREER_DEVELOPMENT:   "Career Development",
    ProductivityState.RESEARCH:             "Research",
    ProductivityState.COMMUNICATION:        "Communication",
    ProductivityState.ADMINISTRATIVE:       "Administrative Work",
    ProductivityState.DISTRACTION:          "Distraction",
    ProductivityState.ENTERTAINMENT:        "Entertainment",
    ProductivityState.BREAK:                "Taking a Break",
    ProductivityState.IDLE:                 "Idle",
    ProductivityState.UNKNOWN:              "Unknown",
}

# Default suggestions per state
_SUGGESTIONS: dict[ProductivityState, str] = {
    ProductivityState.SOFTWARE_DEVELOPMENT: "Deep work in progress. Protect this session.",
    ProductivityState.CAREER_DEVELOPMENT:   "Job search active. Set a 45-minute timer to stay focused.",
    ProductivityState.RESEARCH:             "Research session. Log your findings as you go.",
    ProductivityState.COMMUNICATION:        "Batch your messages then return to focused work.",
    ProductivityState.ADMINISTRATIVE:       "Finish admin tasks and return to your primary goal.",
    ProductivityState.DISTRACTION:          "Close the tab. Return to your last work task.",
    ProductivityState.ENTERTAINMENT:        "Entertainment mode active. Is this intentional?",
    ProductivityState.BREAK:                "Enjoy the break. Return on schedule.",
    ProductivityState.IDLE:                 "System idle. Ready when you are.",
    ProductivityState.UNKNOWN:              "Activity unclear. Open a work task to begin.",
}

# Work-block escalations
_WORK_BLOCK_OVERRIDES: dict[ProductivityState, str] = {
    ProductivityState.DISTRACTION:   "Work block active — close the distraction now.",
    ProductivityState.ENTERTAINMENT: "Work block active — switch to a productive task.",
    ProductivityState.BREAK:         "Work block active — consider returning to work.",
    ProductivityState.IDLE:          "Work block active — what are you working on today?",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_work_block(ts: float, work_blocks: list[dict]) -> bool:
    dt       = datetime.fromtimestamp(ts)
    hour_frac = dt.hour + dt.minute / 60.0
    for block in work_blocks:
        if block.get("start", 0) <= hour_frac < block.get("end", 24):
            return True
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def derive_context(
    snapshots: list,             # Snapshot ORM objects, newest first
    work_blocks: list[dict],
) -> Context:
    now          = time.time()
    in_work_block = _is_work_block(now, work_blocks)

    if not snapshots:
        state = ProductivityState.IDLE
        return Context(
            current_task            = _TASK_LABELS[state],
            productivity_state      = state,
            confidence              = 0.5,
            suggested_action        = _WORK_BLOCK_OVERRIDES.get(state, _SUGGESTIONS[state]) if in_work_block else _SUGGESTIONS[state],
            dominant_app            = "",
            dominant_classification = "",
            window_count            = 0,
            is_work_block           = in_work_block,
        )

    # ── Recency-weighted classification counts ────────────────────────────────
    class_weights: dict[str, float] = {}
    app_counts:    dict[str, int]   = {}
    domains:       set[str]         = set()

    for i, snap in enumerate(snapshots):
        w   = 1.0 / (1.0 + i * RECENCY_DECAY)
        cls = snap.classification or "unknown"
        class_weights[cls] = class_weights.get(cls, 0.0) + w

        app = snap.process_name or "unknown"
        app_counts[app] = app_counts.get(app, 0) + 1

        if snap.active_domain:
            domains.add(snap.active_domain.lower())

    total_weight  = sum(class_weights.values()) or 1.0
    dominant_cls  = max(class_weights, key=class_weights.get)
    dominant_app  = max(app_counts,    key=app_counts.get)
    dominant_ratio = class_weights[dominant_cls] / total_weight

    # ── Combination rules (most specific first) ───────────────────────────────
    active_classes = frozenset(class_weights.keys())
    state:      Optional[ProductivityState] = None
    confidence: float = 0.0

    for req_set, combo_state, base_conf in _COMBO_RULES:
        if req_set.issubset(active_classes):
            combo_weight  = sum(class_weights.get(c, 0) for c in req_set)
            combo_ratio   = combo_weight / total_weight
            adjusted      = base_conf * (0.65 + 0.35 * combo_ratio)
            if adjusted > confidence:
                state      = combo_state
                confidence = adjusted

    # ── Single-class fallback ────────────────────────────────────────────────
    if state is None:
        state      = _SINGLE_MAP.get(dominant_cls, ProductivityState.UNKNOWN)
        confidence = 0.35 + 0.45 * dominant_ratio

    # ── Career development domain override ───────────────────────────────────
    if dominant_cls == "browser":
        for domain in domains:
            if any(kw in domain for kw in _CAREER_KEYWORDS):
                state      = ProductivityState.CAREER_DEVELOPMENT
                confidence = min(confidence + 0.2, 0.95)
                break

    confidence = round(min(confidence, 1.0), 3)

    # ── Suggestion (work-block escalation if relevant) ────────────────────────
    suggestion = (
        _WORK_BLOCK_OVERRIDES.get(state) if in_work_block else None
    ) or _SUGGESTIONS.get(state, "Keep going.")

    return Context(
        current_task            = _TASK_LABELS.get(state, "Unknown"),
        productivity_state      = state,
        confidence              = confidence,
        suggested_action        = suggestion,
        dominant_app            = dominant_app,
        dominant_classification = dominant_cls,
        window_count            = len(snapshots),
        is_work_block           = in_work_block,
    )

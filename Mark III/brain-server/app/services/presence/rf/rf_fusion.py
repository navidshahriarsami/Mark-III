"""
MARK III Phase 15E.5 — Presence Fusion Engine

Combines keyboard, mouse, application, microphone, and RF signals
into a single PresenceEstimate with a confidence score and state label.

Fusion weights (current — no phone/watch yet):
    Keyboard      30%
    Mouse         20%
    RF / WiFi     20%
    Microphone    15%
    Application   15%

Weights sum to 100%.  When phone/watch sensors are added in Phase 20,
the RF weight stays and keyboard/mouse weights are reduced proportionally.

State decision table:
    Score >= 0.88 AND recent_input          → ACTIVE   (intensive use)
    Score >= 0.68 AND recent_input          → WORKING  (normal use)
    Score >= 0.55 AND rf.movement_detected  → PRESENT  (at desk, not typing)
    Score >= 0.35 AND recent_rf             → IDLE     (present but inactive)
    Score >= 0.10                           → AWAY     (no evidence of presence)
    Score  < 0.10                           → UNKNOWN

MARK does not detect humans.  MARK estimates presence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.services.presence.rf.rf_sensor import RFSignal


# ─────────────────────────────────────────────────────────────────
# Presence states
# ─────────────────────────────────────────────────────────────────

class PresenceState(str, Enum):
    ACTIVE   = "active"    # Active keyboard/mouse input in last 30 s
    WORKING  = "working"   # Input in last 5 min — productive session
    PRESENT  = "present"   # RF motion but no direct input (watching screen, thinking)
    IDLE     = "idle"      # No input, some RF evidence — nearby but not active
    AWAY     = "away"      # No input, no RF — likely left the desk/room
    UNKNOWN  = "unknown"   # Sensor data insufficient to estimate


# ─────────────────────────────────────────────────────────────────
# Presence estimate
# ─────────────────────────────────────────────────────────────────

@dataclass
class PresenceEstimate:
    present:    bool
    confidence: float          # 0.0–1.0
    state:      str            # PresenceState value
    evidence:   list[str]      # human-readable signals that contributed
    timestamp:  datetime       = field(default_factory=datetime.now)

    # Raw component scores (for diagnostics)
    keyboard_score:    float = 0.0
    mouse_score:       float = 0.0
    rf_score:          float = 0.0
    mic_score:         float = 0.0
    app_score:         float = 0.0

    @classmethod
    def unknown(cls) -> "PresenceEstimate":
        return cls(
            present    = False,
            confidence = 0.0,
            state      = PresenceState.UNKNOWN,
            evidence   = ["No sensor data available"],
        )

    def to_dict(self) -> dict:
        return {
            "present":    self.present,
            "confidence": round(self.confidence, 3),
            "state":      self.state,
            "evidence":   self.evidence,
            "timestamp":  self.timestamp.isoformat(timespec="seconds"),
            "scores": {
                "keyboard": round(self.keyboard_score, 2),
                "mouse":    round(self.mouse_score,    2),
                "rf":       round(self.rf_score,       2),
                "mic":      round(self.mic_score,      2),
                "app":      round(self.app_score,      2),
            },
        }


# ─────────────────────────────────────────────────────────────────
# Fusion constants
# ─────────────────────────────────────────────────────────────────

# How long ago (seconds) an event counts as "recent"
_KEYBOARD_ACTIVE_S  = 30     # typing in last 30s → fully active
_KEYBOARD_WORKING_S = 300    # typing in last 5min → working
_KEYBOARD_IDLE_S    = 1800   # typing in last 30min → idle
_MOUSE_ACTIVE_S     = 30
_MOUSE_WORKING_S    = 300
_MIC_RECENT_S       = 60     # spoke in last 60s
_APP_RECENT_S       = 120    # app change in last 2min

# Component weights (must sum to 1.0)
_W_KEYBOARD = 0.30
_W_MOUSE    = 0.20
_W_RF       = 0.20
_W_MIC      = 0.15
_W_APP      = 0.15


# ─────────────────────────────────────────────────────────────────
# Fusion engine
# ─────────────────────────────────────────────────────────────────

class PresenceFusion:
    """
    Stateless fusion engine.  Call fuse() each polling cycle.
    All timing arguments are in seconds-since-epoch (time.time()).
    Pass 0.0 for an event that has never occurred.
    """

    def fuse(
        self,
        last_keyboard_s:  float,
        last_mouse_s:     float,
        last_mic_s:       float,
        last_app_s:       float,
        rf:               Optional[RFSignal],
    ) -> PresenceEstimate:
        now      = time.time()
        evidence: list[str] = []

        # ── Keyboard score ────────────────────────────────────────
        kb_age = now - last_keyboard_s if last_keyboard_s > 0 else float("inf")
        if kb_age <= _KEYBOARD_ACTIVE_S:
            kb_score = 1.0;  evidence.append("keyboard active")
        elif kb_age <= _KEYBOARD_WORKING_S:
            kb_score = 0.75; evidence.append("keyboard recent")
        elif kb_age <= _KEYBOARD_IDLE_S:
            kb_score = 0.3;  evidence.append("keyboard idle")
        else:
            kb_score = 0.0

        # ── Mouse score ───────────────────────────────────────────
        ms_age = now - last_mouse_s if last_mouse_s > 0 else float("inf")
        if ms_age <= _MOUSE_ACTIVE_S:
            ms_score = 1.0;  evidence.append("mouse active")
        elif ms_age <= _MOUSE_WORKING_S:
            ms_score = 0.7;  evidence.append("mouse recent")
        else:
            ms_score = 0.0

        # ── Microphone score ──────────────────────────────────────
        mic_age = now - last_mic_s if last_mic_s > 0 else float("inf")
        if mic_age <= _MIC_RECENT_S:
            mic_score = 0.9; evidence.append("voice detected")
        else:
            mic_score = 0.0

        # ── Application score ─────────────────────────────────────
        app_age = now - last_app_s if last_app_s > 0 else float("inf")
        if app_age <= _APP_RECENT_S:
            app_score = 0.6; evidence.append("app activity")
        else:
            app_score = 0.0

        # ── RF score ──────────────────────────────────────────────
        if rf is None or rf.confidence == 0.0:
            rf_score = 0.0
        elif rf.movement_detected:
            rf_score = rf.confidence; evidence.append(f"RF motion ({rf.source})")
        else:
            # Sensor online but no motion — weak presence signal
            rf_score = rf.confidence * 0.15

        # ── Weighted fusion ───────────────────────────────────────
        score = (
            kb_score  * _W_KEYBOARD +
            ms_score  * _W_MOUSE    +
            rf_score  * _W_RF       +
            mic_score * _W_MIC      +
            app_score * _W_APP
        )
        score = max(0.0, min(1.0, score))

        # ── State decision ────────────────────────────────────────
        recent_input = kb_age <= _KEYBOARD_WORKING_S or ms_age <= _MOUSE_WORKING_S
        rf_motion    = rf is not None and rf.movement_detected

        if score >= 0.88 and recent_input:
            state   = PresenceState.ACTIVE
            present = True
        elif score >= 0.68 and recent_input:
            state   = PresenceState.WORKING
            present = True
        elif score >= 0.55 and rf_motion:
            state   = PresenceState.PRESENT
            present = True
        elif score >= 0.35:
            state   = PresenceState.IDLE
            present = True
        elif score >= 0.10:
            state   = PresenceState.AWAY
            present = False
        else:
            state   = PresenceState.UNKNOWN
            present = False

        if not evidence:
            evidence.append("no sensor activity")

        return PresenceEstimate(
            present         = present,
            confidence      = round(score, 3),
            state           = state.value,
            evidence        = evidence,
            keyboard_score  = round(kb_score,  2),
            mouse_score     = round(ms_score,  2),
            rf_score        = round(rf_score,  2),
            mic_score       = round(mic_score, 2),
            app_score       = round(app_score, 2),
        )

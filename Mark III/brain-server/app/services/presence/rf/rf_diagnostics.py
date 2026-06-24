"""
MARK III Phase 15E.5 — RF Presence Diagnostics

Rolling JSON log of presence events (last 500).
Written to brain-server/rf_events.json.

Each event records:
    timestamp, state, confidence, movement, rf_source, evidence
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from app.services.presence.rf.rf_fusion   import PresenceEstimate
from app.services.presence.rf.rf_sensor   import RFSignal

log = logging.getLogger("markiii.presence.diag")

_BRAIN_SERVER = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
_LOG_PATH = os.path.join(_BRAIN_SERVER, "rf_events.json")


class RFDiagnostics:
    """Rolling presence event log — last 500 events, written asynchronously."""

    _MAX = 500

    def __init__(self, path: str = _LOG_PATH) -> None:
        self._path  = path
        self._lock  = threading.Lock()
        self._events: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f).get("events", [])
        except Exception:
            return []

    def record(
        self,
        estimate: PresenceEstimate,
        rf: Optional[RFSignal] = None,
    ) -> None:
        event = {
            "timestamp":  datetime.now().isoformat(timespec="seconds"),
            "state":      estimate.state,
            "confidence": estimate.confidence,
            "present":    estimate.present,
            "evidence":   estimate.evidence,
            "scores": {
                "keyboard": estimate.keyboard_score,
                "mouse":    estimate.mouse_score,
                "rf":       estimate.rf_score,
                "mic":      estimate.mic_score,
                "app":      estimate.app_score,
            },
            "rf": {
                "source":            rf.source            if rf else None,
                "movement_detected": rf.movement_detected if rf else None,
                "signal_strength":   rf.signal_strength   if rf else None,
                "confidence":        rf.confidence        if rf else None,
                "zone":              rf.zone              if rf else None,
            },
        }
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._MAX:
                self._events = self._events[-self._MAX:]

        threading.Thread(target=self._write, daemon=True).start()

    def _write(self) -> None:
        try:
            with self._lock:
                data = {"events": list(self._events)}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.debug("Diagnostics write failed: %s", e)

    def summary(self) -> dict:
        with self._lock:
            if not self._events:
                return {"events_logged": 0}
            recent = self._events[-20:]

        from collections import Counter
        states = Counter(e["state"] for e in recent)
        avg_conf = sum(e["confidence"] for e in recent) / len(recent)
        motion_pct = sum(
            1 for e in recent if e.get("rf", {}) and e["rf"].get("movement_detected")
        ) / len(recent) * 100

        return {
            "events_logged":   len(self._events),
            "recent_states":   dict(states),
            "avg_confidence":  round(avg_conf, 3),
            "rf_motion_pct":   round(motion_pct, 1),
            "last_state":      self._events[-1]["state"] if self._events else "unknown",
        }

    def last_event(self) -> Optional[dict]:
        with self._lock:
            return self._events[-1] if self._events else None

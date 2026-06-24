"""
MARK III Phase 16 — Presence Fusion

Determines which device the user is most likely on right now by fusing
signals from all registered mesh devices.

Signals (highest to lowest weight):
  1. device.active flag  — client explicitly says user is here
  2. device.state        — ACTIVE > ONLINE > IDLE > OFFLINE
  3. Heartbeat recency   — exponential decay; full score if < 30s old
  4. Device type         — mobile/wearable slightly preferred over desktop
     (desktop is always there; a phone in hand = stronger presence signal)

Output: PresenceResult — active device, confidence 0–1, evidence list.

Used by:
  - MeshManager.get_active_device() (lightweight shortcut)
  - Voice loop: decide where to send a response
  - Reflex presence_module.py: "where am I?"
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PresenceResult:
    device_id:     str
    device_name:   str
    confidence:    float                # 0.0–1.0
    state:         str                  # DeviceState value of winning device
    evidence:      list[str] = field(default_factory=list)
    all_scores:    dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        pct = int(self.confidence * 100)
        ev  = ", ".join(self.evidence[:2]) if self.evidence else "no signals"
        return f"User most likely on {self.device_name} ({pct}% confidence — {ev})."


# Weight constants
_W_ACTIVE_FLAG  = 0.40   # device.active == True
_W_STATE        = 0.30   # ACTIVE > ONLINE/IDLE
_W_RECENCY      = 0.20   # how fresh is the heartbeat?
_W_TYPE_MOBILE  = 0.10   # phone/watch > desktop (mobile = user in hand)

# State scores (0–1)
_STATE_SCORES = {
    "active":  1.0,
    "online":  0.5,
    "idle":    0.2,
    "offline": 0.0,
}

# Type mobility scores (higher = stronger presence signal when active)
_TYPE_SCORES = {
    "iphone":  1.0,
    "watch":   0.9,
    "macbook": 0.7,
    "desktop": 0.3,   # always present; not distinctive
    "unknown": 0.5,
}

# Recency: full score within FRESH_S, then exponential decay
_FRESH_S    = 30.0    # seconds
_HALF_LIFE  = 60.0    # score halves every 60 s


def _recency_score(last_seen: datetime) -> float:
    age_s = max(0.0, (datetime.now() - last_seen).total_seconds())
    if age_s <= _FRESH_S:
        return 1.0
    return math.exp(-math.log(2) * (age_s - _FRESH_S) / _HALF_LIFE)


def fuse(devices: list) -> Optional[PresenceResult]:
    """
    Fuse presence signals from all devices.
    Returns None only if the device list is completely empty.

    devices: list[Device]  (imported lazily to avoid circular imports)
    """
    if not devices:
        return None

    scores:   dict[str, float] = {}
    evidence: dict[str, list[str]] = {}

    for d in devices:
        if d.state == "offline":
            scores[d.device_id]   = 0.0
            evidence[d.device_id] = ["offline"]
            continue

        ev: list[str] = []
        score = 0.0

        # 1. Active flag
        if d.active:
            score += _W_ACTIVE_FLAG
            ev.append("user active flag")

        # 2. State
        ss = _STATE_SCORES.get(d.state, 0.0)
        score += _W_STATE * ss
        if ss > 0.5:
            ev.append(f"state={d.state}")

        # 3. Heartbeat recency
        rec = _recency_score(d.last_seen)
        score += _W_RECENCY * rec
        age_s = max(0.0, (datetime.now() - d.last_seen).total_seconds())
        if age_s < _FRESH_S:
            ev.append(f"heartbeat {age_s:.0f}s ago")
        elif rec > 0.5:
            ev.append(f"heartbeat recent ({age_s:.0f}s)")

        # 4. Device type mobility bonus
        type_s = _TYPE_SCORES.get(d.type.lower(), 0.5)
        score += _W_TYPE_MOBILE * type_s

        # Battery charging → device is plugged in → user might not be holding it
        if d.battery is not None and d.battery > 95 and d.type in ("iphone", "watch"):
            score *= 0.8   # slight penalty when phone/watch is fully charged (probably docked)
            ev.append("possibly charging/docked")

        scores[d.device_id]   = round(score, 4)
        evidence[d.device_id] = ev

    if not scores:
        return None

    # Winning device
    best_id = max(scores, key=scores.get)
    best_s  = scores[best_id]
    total   = sum(scores.values())
    confidence = (best_s / total) if total > 0 else 0.0

    best_device = next((d for d in devices if d.device_id == best_id), devices[0])

    return PresenceResult(
        device_id   = best_id,
        device_name = best_device.name,
        confidence  = round(confidence, 3),
        state       = best_device.state,
        evidence    = evidence.get(best_id, []),
        all_scores  = scores,
    )

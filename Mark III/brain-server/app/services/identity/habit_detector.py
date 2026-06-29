"""
MARK III — Habit Detector

Identifies recurring behavioral patterns from activity data.
A habit requires consistent repetition before it becomes a preference.

Confidence model:
  3 occurrences  → candidate (not stored)
  7 occurrences  → weak habit (stored with low confidence)
  15 occurrences → confirmed habit (stored with high confidence)
  30 occurrences → strong habit (updates UserProfile directly)

Examples of detected habits:
  "User opens VS Code between 08:00-09:00 every weekday"
  "User checks system status every morning"
  "User works on MARK III after 20:00"
  "User prefers 1-sentence answers for casual queries"
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("markiii.identity.habits")

_HABITS_PATH = Path(__file__).parents[3] / "habit_data.json"

CANDIDATE_THRESHOLD = 3
WEAK_THRESHOLD      = 7
CONFIRMED_THRESHOLD = 15
STRONG_THRESHOLD    = 30


@dataclass
class Habit:
    key:         str      # unique identifier e.g. "morning_vscode"
    description: str      # human-readable
    category:    str      # "app" | "time" | "query" | "workflow" | "preference"
    count:       int      = 0
    confidence:  float    = 0.0
    first_seen:  str      = ""
    last_seen:   str      = ""
    confirmed:   bool     = False

    def update(self) -> None:
        self.last_seen  = datetime.now().isoformat(timespec="seconds")
        self.count     += 1
        self.confidence = min(self.count / STRONG_THRESHOLD, 1.0)
        self.confirmed  = self.count >= CONFIRMED_THRESHOLD
        if not self.first_seen:
            self.first_seen = self.last_seen


class HabitDetector:
    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._habits: dict[str, Habit] = {}
        self._load()

    def _load(self) -> None:
        if _HABITS_PATH.exists():
            try:
                data = json.loads(_HABITS_PATH.read_text())
                for k, v in data.items():
                    self._habits[k] = Habit(**v)
                log.debug("Loaded %d habits", len(self._habits))
            except Exception:
                pass

    def _save(self) -> None:
        try:
            data = {k: vars(v) for k, v in self._habits.items()}
            _HABITS_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.debug("Habit save error: %s", e)

    def observe(self, key: str, description: str, category: str) -> Optional[Habit]:
        """
        Record an observation. Returns the habit if it crossed a threshold.
        """
        with self._lock:
            if key not in self._habits:
                self._habits[key] = Habit(key=key, description=description, category=category)
            h = self._habits[key]
            h.update()
            self._save()

            # Return habit when it crosses meaningful thresholds
            if h.count in (WEAK_THRESHOLD, CONFIRMED_THRESHOLD, STRONG_THRESHOLD):
                log.info(
                    "Habit %s: count=%d confidence=%.0f%%  %s",
                    key, h.count, h.confidence * 100, description,
                )
                return h
        return None

    def observe_morning_app(self, app_name: str) -> None:
        hour = datetime.now().hour
        if 5 <= hour <= 11:
            self.observe(
                key         = f"morning_{app_name.lower().replace(' ', '_')}",
                description = f"User uses {app_name} in the morning",
                category    = "app",
            )

    def observe_late_work(self) -> None:
        hour = datetime.now().hour
        if hour >= 20 or hour <= 3:
            self.observe(
                key         = "late_evening_work",
                description = "User works late (after 20:00)",
                category    = "time",
            )

    def observe_query_type(self, intent: str) -> None:
        hour = datetime.now().hour
        period = "morning" if 5 <= hour <= 11 else "afternoon" if 12 <= hour <= 17 else "evening"
        self.observe(
            key         = f"{period}_{intent}_queries",
            description = f"User frequently asks {intent} questions in the {period}",
            category    = "query",
        )

    def get_confirmed_habits(self) -> list[Habit]:
        with self._lock:
            return [h for h in self._habits.values() if h.confirmed]

    def get_profile_insights(self) -> str:
        """Returns a text summary of confirmed habits for Qwen context."""
        confirmed = self.get_confirmed_habits()
        if not confirmed:
            return ""
        lines = ["OBSERVED PATTERNS:"]
        for h in confirmed[:5]:
            lines.append(f"- {h.description} (confidence: {h.confidence:.0%})")
        return "\n".join(lines)

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_habits":     len(self._habits),
                "confirmed_habits": sum(1 for h in self._habits.values() if h.confirmed),
                "strong_habits":    sum(1 for h in self._habits.values() if h.count >= STRONG_THRESHOLD),
            }


_detector: Optional[HabitDetector] = None
_det_lock = threading.Lock()


def get_habit_detector() -> HabitDetector:
    global _detector
    if _detector is None:
        with _det_lock:
            if _detector is None:
                _detector = HabitDetector()
    return _detector

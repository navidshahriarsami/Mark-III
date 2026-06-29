"""
MARK III — Activity Tracker

Tracks usage patterns to improve personalization over time.
Stores only meaningful behavioural signals — not raw conversation logs.

Tracked:
  - Query type frequencies (what the owner asks about most)
  - Active hours (when MARK is used)
  - Device usage patterns
  - Repeated commands / workflows
  - Application mentions
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.identity.activity")

_ACTIVITY_PATH = Path(__file__).parents[3] / "activity_data.json"


class ActivityTracker:
    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._data  = self._load()

    def _load(self) -> dict:
        if _ACTIVITY_PATH.exists():
            try:
                return json.loads(_ACTIVITY_PATH.read_text())
            except Exception:
                pass
        return {
            "query_types":    defaultdict(int),
            "active_hours":   defaultdict(int),
            "app_mentions":   defaultdict(int),
            "device_usage":   defaultdict(int),
            "weekly_pattern": defaultdict(int),
            "total_sessions": 0,
            "total_queries":  0,
        }

    def _save(self) -> None:
        try:
            data = {k: dict(v) if isinstance(v, defaultdict) else v
                    for k, v in self._data.items()}
            _ACTIVITY_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.debug("Activity save error: %s", e)

    def record_query(self, text: str, intent: str, device: str = "desktop") -> None:
        """Record a query for pattern learning."""
        now = datetime.now()
        with self._lock:
            self._data["query_types"][intent]    = self._data["query_types"].get(intent, 0) + 1
            self._data["active_hours"][now.hour] = self._data["active_hours"].get(now.hour, 0) + 1
            self._data["weekly_pattern"][now.strftime("%A")] = \
                self._data["weekly_pattern"].get(now.strftime("%A"), 0) + 1
            self._data["device_usage"][device]   = self._data["device_usage"].get(device, 0) + 1
            self._data["total_queries"]          = self._data.get("total_queries", 0) + 1

    def record_session_end(self) -> None:
        with self._lock:
            self._data["total_sessions"] = self._data.get("total_sessions", 0) + 1
        self._save()

    def get_insights(self) -> dict:
        """Return behavioural insights for the learning engine."""
        with self._lock:
            qt   = dict(self._data.get("query_types", {}))
            ah   = dict(self._data.get("active_hours", {}))
            wp   = dict(self._data.get("weekly_pattern", {}))
            peak_hour = max(ah, key=ah.get) if ah else None
            top_intent = max(qt, key=qt.get) if qt else None
            return {
                "total_queries":  self._data.get("total_queries", 0),
                "total_sessions": self._data.get("total_sessions", 0),
                "top_intent":     top_intent,
                "peak_hour":      peak_hour,
                "query_types":    qt,
                "active_hours":   ah,
                "weekly_pattern": wp,
            }


_tracker: ActivityTracker | None = None
_tracker_lock = threading.Lock()


def get_activity_tracker() -> ActivityTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ActivityTracker()
    return _tracker

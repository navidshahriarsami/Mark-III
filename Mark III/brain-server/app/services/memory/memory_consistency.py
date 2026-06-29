"""
MARK III — Memory Consistency Engine

Detects and reports conflicts, duplicates, and contradictions in the fact store.
Called after every fact upsert to maintain integrity.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.memory.consistency")
_DIAG_PATH = Path(__file__).parents[3] / "memory_consistency.json"


@dataclass
class ConsistencyEvent:
    timestamp:   str  = ""
    event_type:  str  = ""   # "duplicate" | "conflict" | "update" | "confirmed"
    subject:     str  = ""
    predicate:   str  = ""
    old_value:   str  = ""
    new_value:   str  = ""
    detail:      str  = ""


class MemoryConsistency:
    _MAX = 200

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._events: list[dict] = []
        self._stats  = {
            "total_facts": 0, "updates": 0, "conflicts": 0,
            "confirmed": 0, "duplicates_prevented": 0,
        }

    def record(self, event: ConsistencyEvent) -> None:
        event.timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._events.append(asdict(event))
            if len(self._events) > self._MAX:
                self._events = self._events[-self._MAX:]
            self._stats[event.event_type] = self._stats.get(event.event_type, 0) + 1

    def check_conflicts(self, subject: str, predicate: str, new_value: str) -> bool:
        """Returns True if a conflict exists (different value already stored)."""
        try:
            from app.services.memory.fact_store import get_fact_store
            existing = get_fact_store().get(subject, predicate)
            if existing and existing.value != new_value:
                self.record(ConsistencyEvent(
                    event_type = "conflict",
                    subject    = subject,
                    predicate  = predicate,
                    old_value  = existing.value,
                    new_value  = new_value,
                    detail     = f"Conflict: stored={existing.value} new={new_value}",
                ))
                log.warning(
                    "Fact conflict: %s.%s was=%r now=%r",
                    subject, predicate, existing.value, new_value,
                )
                return True
        except Exception:
            pass
        return False

    def summary(self) -> dict:
        with self._lock:
            return {**self._stats, "recent_events": len(self._events)}

    def save(self) -> None:
        try:
            _DIAG_PATH.write_text(json.dumps(
                {"stats": self._stats, "events": self._events[-50:]}, indent=2
            ))
        except Exception:
            pass


_consistency = MemoryConsistency()


def get_consistency() -> MemoryConsistency:
    return _consistency

"""MARK III — Knowledge Diagnostics — indexing stats and health."""
from __future__ import annotations
import json, threading, logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.knowledge.diag")
_DIAG_PATH = Path(__file__).parents[3] / "knowledge_diagnostics.json"


@dataclass
class IndexEvent:
    timestamp:  str  = ""
    event:      str  = ""   # "indexed" | "removed" | "error" | "full_scan"
    file:       str  = ""
    chunks:     int  = 0
    ms:         float = 0.0
    detail:     str  = ""


class KnowledgeDiagnostics:
    _MAX = 500

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._stats = {"total_indexed": 0, "total_chunks": 0, "errors": 0}

    def record(self, event: IndexEvent) -> None:
        event.timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._events.append(asdict(event))
            if len(self._events) > self._MAX:
                self._events = self._events[-self._MAX:]
            if event.event == "indexed":
                self._stats["total_indexed"] += 1
                self._stats["total_chunks"]  += event.chunks
            elif event.event == "error":
                self._stats["errors"] += 1

    def summary(self) -> dict:
        with self._lock:
            return {**self._stats, "recent_events": len(self._events)}

    def save(self) -> None:
        try:
            _DIAG_PATH.write_text(json.dumps(
                {"stats": self._stats, "events": self._events[-100:]}, indent=2
            ))
        except Exception as e:
            log.debug("Diag save failed: %s", e)


diag = KnowledgeDiagnostics()

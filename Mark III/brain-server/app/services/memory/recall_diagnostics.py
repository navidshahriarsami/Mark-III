"""MARK III — Recall Diagnostics — tracks retrieval source and bypass rates."""
from __future__ import annotations
import json, threading, logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("markiii.memory.recall_diag")
_DIAG_PATH = Path(__file__).parents[3] / "recall_diagnostics.json"


@dataclass
class RecallEvent:
    timestamp:   str   = ""
    query:       str   = ""
    source:      str   = ""  # "structured" | "vector" | "obsidian" | "llm"
    found:       bool  = False
    latency_ms:  float = 0.0
    confidence:  float = 0.0


class RecallDiagnostics:
    _MAX = 500

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._events: list[dict] = []
        self._stats = {
            "total_queries": 0,
            "structured_hits": 0, "vector_hits": 0,
            "obsidian_hits": 0, "llm_fallback": 0,
            "llm_bypass_rate": 0.0,
        }

    def record(self, event: RecallEvent) -> None:
        event.timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._events.append(asdict(event))
            if len(self._events) > self._MAX:
                self._events = self._events[-self._MAX:]
            self._stats["total_queries"] += 1
            if event.source == "structured": self._stats["structured_hits"] += 1
            elif event.source == "vector":   self._stats["vector_hits"] += 1
            elif event.source == "obsidian": self._stats["obsidian_hits"] += 1
            else:                            self._stats["llm_fallback"] += 1
            t = self._stats["total_queries"]
            if t:
                bypassed = t - self._stats["llm_fallback"]
                self._stats["llm_bypass_rate"] = round(bypassed / t, 3)

    def summary(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def save(self) -> None:
        try:
            _DIAG_PATH.write_text(json.dumps(
                {"stats": self._stats, "recent": self._events[-50:]}, indent=2))
        except Exception:
            pass


diag = RecallDiagnostics()

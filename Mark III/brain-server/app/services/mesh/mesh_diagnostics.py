"""
MARK III Phase 16A — Mesh Diagnostics

Rolling event log for the device mesh (last 500 events).
Tracks registration, heartbeats, offline transitions, and errors.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime

log = logging.getLogger("markiii.mesh.diag")

_DIAG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "mesh_diagnostics.json")
)
_MAX_EVENTS = 500


@dataclass
class MeshEvent:
    timestamp:   str   = ""
    event_type:  str   = ""    # "register" | "heartbeat" | "online" | "offline" | "error"
    device_id:   str   = ""
    device_name: str   = ""
    latency_ms:  float = 0.0
    detail:      str   = ""


class MeshDiagnostics:
    """Rolling JSON log of mesh events."""

    def __init__(self, path: str = _DIAG_PATH) -> None:
        self._path   = path
        self._lock   = threading.Lock()
        self._events: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f).get("events", [])
        except Exception:
            return []

    def record(self, event: MeshEvent) -> None:
        event.timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._events.append(asdict(event))
            if len(self._events) > _MAX_EVENTS:
                self._events = self._events[-_MAX_EVENTS:]
        threading.Thread(target=self._write, daemon=True).start()

    def _write(self) -> None:
        try:
            with self._lock:
                data = {"events": list(self._events)}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.debug("Mesh diagnostics write: %s", e)

    def summary(self) -> dict:
        with self._lock:
            total = len(self._events)
            by_type: dict[str, int] = {}
            for ev in self._events:
                t = ev.get("event_type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1
            return {"total_events": total, "by_type": by_type}


# Module singleton
diag = MeshDiagnostics()

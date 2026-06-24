from __future__ import annotations

"""
MARK III — Voice Diagnostics  (Phase 14, Part 12)

Tracks per-turn latency and writes a rolling JSON log to
brain-server/voice_diagnostics.json (last 500 sessions).

Usage:
    from app.services.voice.voice_diagnostics import diag, VoiceSession

    s = VoiceSession(tts_backend="xtts")
    s.stt_latency_ms     = 1200.0
    s.council_latency_ms = 2100.0
    s.tts_latency_ms     = 700.0
    s.total_ms           = 4000.0
    diag.record(s)

    print(diag.summary())
    # {'sessions_logged': 1, 'avg_stt_ms': 1200.0, ...}
"""

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime

log = logging.getLogger("markiii.diagnostics")

# brain-server/voice_diagnostics.json
# __file__ is at: brain-server/app/services/voice/voice_diagnostics.py
# dirname × 3 goes:  voice/ → services/ → app/ → brain-server/
_BRAIN_SERVER = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_DIAG_PATH    = os.path.join(_BRAIN_SERVER, "voice_diagnostics.json")


@dataclass
class VoiceSession:
    timestamp:             str   = ""
    wake_latency_ms:       float = 0.0
    speech_detect_ms:      float = 0.0   # Phase 15B: time from WAIT_FOR_SPEECH to first confirmed speech
    listening_duration_ms: float = 0.0   # Phase 15A: full time in LISTENING state (includes silence at end)
    stt_latency_ms:        float = 0.0
    council_latency_ms:    float = 0.0
    tts_latency_ms:        float = 0.0
    total_ms:              float = 0.0
    tts_backend:           str   = "sapi"
    interrupted:           bool  = False
    followup_used:         bool  = False
    reflex_used:           bool  = False  # Phase 15A: True when reflex router skipped LLM
    utterance_chars:       int   = 0
    answer_chars:          int   = 0


class VoiceDiagnostics:
    """Rolling JSON log of voice turn latencies."""

    _MAX = 500

    def __init__(self, path: str = _DIAG_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._log: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f).get("sessions", [])
        except Exception:
            return []

    def record(self, s: VoiceSession) -> None:
        s.timestamp = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._log.append(asdict(s))
            if len(self._log) > self._MAX:
                self._log = self._log[-self._MAX:]
        threading.Thread(target=self._write, daemon=True).start()

    def _write(self) -> None:
        try:
            with self._lock:
                data = {"sessions": list(self._log)}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.debug("Diagnostics write: %s", e)

    def summary(self) -> dict:
        with self._lock:
            if not self._log:
                return {}
            recent = self._log[-20:]

        def avg(key: str) -> float:
            vals = [s[key] for s in recent if s.get(key, 0) > 0]
            return round(sum(vals) / len(vals), 1) if vals else 0.0

        return {
            "sessions_logged": len(self._log),
            "avg_wake_ms":     avg("wake_latency_ms"),
            "avg_stt_ms":      avg("stt_latency_ms"),
            "avg_council_ms":  avg("council_latency_ms"),
            "avg_tts_ms":      avg("tts_latency_ms"),
            "avg_total_ms":    avg("total_ms"),
        }


# Module-level singleton — import and use directly
diag = VoiceDiagnostics()

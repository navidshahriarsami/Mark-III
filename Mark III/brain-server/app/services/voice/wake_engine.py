from __future__ import annotations

"""
MARK III — Wake Word Engine  (Phase 13.7 / 14.0)

IDLE MODE: zero Whisper, zero STT, zero transcription.

Two backends — selected automatically at startup:

  OWW    OpenWakeWord neural detector (~1 ms/frame, ONNX)
         Requires:  pip install openwakeword
         Requires:  a custom "mark.onnx" model at the path below.
         Without the custom model OWW is not loaded (falls back to ENERGY).

  ENERGY Pure energy-gate heuristic (always available, no packages).
         Fires when a speech burst of word-like duration (150–800 ms)
         is detected above the configurable dBFS gate.
         Long background speech (> 800 ms) is ignored automatically.

Neither backend runs Whisper.
Whisper loads in always_listening_loop AFTER the wake event fires.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("markiii.wake")

# ---------------------------------------------------------------------------
# Wake-word vocabulary (used for command parsing on the STT path, not here)
# ---------------------------------------------------------------------------

WAKE_WORDS      = frozenset(["mark", "marc", "marg"])
STOP_WORDS      = frozenset(["stop", "cancel", "quiet", "silence", "enough", "shut"])
SLEEP_WORDS     = frozenset(["sleep", "rest"])
WAKE_RESUME_WDS = frozenset(["wake", "wakeup", "up"])
MUTE_WORDS      = frozenset(["mute", "unmute"])
STATUS_WORDS    = frozenset(["status", "diagnostics"])
RESTART_WORDS   = frozenset(["restart", "reboot"])

# Path to a custom OWW ONNX model for "MARK".
# Train one with:  python -m openwakeword.train --wakeword "mark"
# or download a community model and drop it here.
_OWW_MODEL_PATH = os.path.join(os.path.dirname(__file__), "mark_wakeword.onnx")

_SAMPLE_RATE = 16000
_COOLDOWN_S  = 1.5          # minimum seconds between consecutive wake events

# ---------------------------------------------------------------------------
# WakeEvent — same public contract as before
# ---------------------------------------------------------------------------

@dataclass
class WakeEvent:
    """Emitted when the wake word is detected."""
    transcript:  str
    command:     str    # "" for a normal wake; populated only when user explicitly
                        # says "MARK sleep" / "MARK stop" etc. via conversation STT
    confidence:  float
    detected_at: float = field(default_factory=time.monotonic)

    @property
    def is_command_only(self) -> bool:
        return bool(self.command)

    @property
    def query(self) -> str:
        words = self.transcript.split()
        while words and words[0].strip(".,!?;:") in WAKE_WORDS:
            words = words[1:]
        return " ".join(words).strip()


# ---------------------------------------------------------------------------
# Backend: OpenWakeWord (OWW)
# ---------------------------------------------------------------------------

class _OWWBackend:
    """
    OpenWakeWord ONNX detector.

    Loads a custom "mark.onnx" model.  Each 30 ms PCM chunk is fed directly
    to OWW (it handles internal buffering); returns the activation score.

    Install:  pip install openwakeword
    Model:    train with openwakeword CLI or download a community model and
              place it at _OWW_MODEL_PATH.
    """

    def __init__(self, model_path: str, sensitivity: float) -> None:
        from openwakeword.model import Model   # ImportError if not installed

        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"OWW custom model not found: {model_path}\n"
                "Train with:  python -m openwakeword.train --wakeword mark\n"
                "Falling back to energy-gate backend."
            )

        self._model     = Model(wakeword_models=[model_path], inference_framework="onnx")
        self._key       = os.path.splitext(os.path.basename(model_path))[0]
        # sensitivity 1.0 → threshold 0.30  (very sensitive)
        # sensitivity 0.7 → threshold 0.51  (recommended)
        # sensitivity 0.0 → threshold 0.80  (strict)
        self._threshold = round(max(0.30, min(0.80, 1.0 - sensitivity * 0.70)), 2)
        log.info(
            "OWW backend: model=%r  key=%r  threshold=%.2f",
            model_path, self._key, self._threshold,
        )

    def feed(self, pcm16: np.ndarray) -> float:
        preds = self._model.predict(pcm16)
        return float(preds.get(self._key, 0.0))

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def name(self) -> str:
        return "openwakeword"


# ---------------------------------------------------------------------------
# Backend: Energy gate  (always available, no dependencies, no neural nets)
# ---------------------------------------------------------------------------

class _EnergyBackend:
    """
    Keyword-duration energy heuristic — no packages required.

    Algorithm:
      1. Chunk energy RMS is computed (< 0.01 % CPU on any modern CPU).
      2. When RMS exceeds the gate:
            begin accumulating a "speech burst".
      3. The burst ends when 100 ms of silence follows, OR when the burst
            exceeds MAX_SPEECH_MS (which means it's a long utterance, not
            a single wake word — ignored).
      4. If the burst is between MIN_SPEECH_MS and MAX_SPEECH_MS:
            return confidence = 1.0 → wake detected.

    False-positive profile:
      - A single clap or door slam: too short (< 150 ms) → ignored.
      - Background conversation: too long (> 800 ms) → ignored.
      - A single sharp word at the right volume: fires.
    This is sufficient for a single-user home / office environment.
    """

    _GATE_DB_BASE  = -35.0   # default gate at sensitivity = 0.7
    _GATE_DB_RANGE = 20.0    # range across 0.0 – 1.0
    _MIN_MS        = 150     # shortest word-like event
    _MAX_MS        = 800     # longest single-word event (guards vs. sentences)
    _SIL_END_MS    = 100     # silence to declare the word finished

    def __init__(self, sample_rate: int, sensitivity: float) -> None:
        self._gate_db = (
            self._GATE_DB_BASE - (sensitivity - 0.5) * self._GATE_DB_RANGE
        )
        self._min_sp  = int(self._MIN_MS    / 1000 * sample_rate)
        self._max_sp  = int(self._MAX_MS    / 1000 * sample_rate)
        self._sil_end = int(self._SIL_END_MS / 1000 * sample_rate)

        self._in_word  = False
        self._sp_count = 0
        self._sil_ct   = 0

        log.info(
            "Energy backend: gate=%.1f dBFS  word_dur=[%d–%d ms]",
            self._gate_db, self._MIN_MS, self._MAX_MS,
        )

    def feed(self, pcm16: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(pcm16.astype(np.float64) ** 2)))
        db  = 20.0 * np.log10(rms / 32768.0 + 1e-9)
        n   = len(pcm16)

        if not self._in_word:
            if db >= self._gate_db:
                self._in_word  = True
                self._sp_count = n
                self._sil_ct   = 0
            return 0.0

        # Currently inside a speech burst
        if db >= self._gate_db:
            self._sp_count += n
            self._sil_ct    = 0
        else:
            self._sil_ct += n

        # Burst too long → must be a sentence, not "MARK" → abort
        if self._sp_count > self._max_sp:
            self._in_word  = False
            self._sp_count = 0
            return 0.0

        # Silence after speech → word is over
        if self._sil_ct >= self._sil_end:
            sp             = self._sp_count
            self._in_word  = False
            self._sp_count = 0
            if sp >= self._min_sp:
                return 1.0

        return 0.0

    @property
    def threshold(self) -> float:
        return 0.9   # only exact 1.0 fires, this guards floating-point noise

    @property
    def name(self) -> str:
        return "energy_gate"


# ---------------------------------------------------------------------------
# WakeEngine — public API (same as before)
# ---------------------------------------------------------------------------

class WakeEngine:
    """
    Whisper-free wake word engine for MARK III.

    Usage (identical to the old API):
        engine = WakeEngine(sensitivity=0.7)
        engine.load()                      # no-op; compat shim
        engine.feed(pcm16, callback=fn)    # call per 30 ms chunk
        engine.is_loaded                   # True once backend is ready

    set_shared_model() is a no-op — this engine does not use Whisper.
    """

    def __init__(self, sensitivity: float = 0.7) -> None:
        self._sensitivity = max(0.0, min(1.0, sensitivity))
        self._last_wake   = 0.0
        self._backend: Optional[_OWWBackend | _EnergyBackend] = None
        self._loaded      = False
        self._select_backend()

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _select_backend(self) -> None:
        # Try OpenWakeWord with custom ONNX model
        try:
            self._backend = _OWWBackend(_OWW_MODEL_PATH, self._sensitivity)
            log.info("Wake engine: OpenWakeWord backend selected")
        except Exception as e:
            log.info("Wake engine: OWW not available (%s)", e)
            log.info("Wake engine: energy-gate backend selected (no ML, no Whisper)")
            self._backend = _EnergyBackend(_SAMPLE_RATE, self._sensitivity)
        self._loaded = True

    # ------------------------------------------------------------------
    # Lifecycle shims (keep API compatibility with old engine)
    # ------------------------------------------------------------------

    def set_shared_model(self, model, lock: threading.Lock) -> None:
        """No-op: this engine does not use Whisper in IDLE mode."""
        log.debug("Wake engine: set_shared_model() ignored (Whisper-free engine)")

    def load(self) -> None:
        """No-op: backend is selected in __init__."""
        pass

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Main feed loop — called per 30 ms chunk from dispatch thread
    # ------------------------------------------------------------------

    def feed(
        self,
        pcm16:    np.ndarray,
        callback: Callable[[WakeEvent], None] = None,
    ) -> None:
        """
        Feed one 30 ms int16 PCM chunk.
        Non-blocking.  If wake detected, callback(WakeEvent) is called
        synchronously from this thread (fast: no Whisper, no I/O).
        """
        if not self._backend:
            return

        confidence = self._backend.feed(pcm16)

        if confidence < self._backend.threshold:
            return

        now = time.monotonic()
        if (now - self._last_wake) < _COOLDOWN_S:
            return

        self._last_wake = now
        log.info(
            "Wake detected  backend=%s  confidence=%.2f",
            self._backend.name, confidence,
        )

        event = WakeEvent(
            transcript  = "mark",
            command     = "",
            confidence  = confidence,
            detected_at = now,
        )

        if callback:
            callback(event)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "engine":      self._backend.name if self._backend else "none",
            "loaded":      self._loaded,
            "sensitivity": self._sensitivity,
            "whisper":     False,
        }

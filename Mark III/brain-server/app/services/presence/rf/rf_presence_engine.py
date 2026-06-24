"""
MARK III Phase 15E.5 — RF Presence Engine

Central orchestrator for multi-source presence estimation.

Sources (current):
    keyboard    — Windows GetLastInputInfo() (covers KB + mouse combined)
    mouse       — same API, separate tracking when available
    microphone  — updated by always_listening_loop.py on each utterance
    application — updated by always_listening_loop.py on state changes
    RF / WiFi   — DummySensor now; EeroSensor / ESP32Sensor in Phase 20

Polling: background thread, every POLL_INTERVAL_S seconds.

Public API:
    engine.start()
    engine.stop()
    engine.record_microphone()          # called from voice pipeline
    engine.record_activity()            # called from voice/tray on user action
    engine.estimate -> PresenceEstimate
    engine.status_dict() -> dict        # for REST API / tray / voice

Singleton: get_presence_engine() returns the module-level instance.

MARK does not detect humans.  MARK estimates presence.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Optional

from app.services.presence.rf.rf_fusion      import PresenceFusion, PresenceEstimate
from app.services.presence.rf.rf_sensor      import RFSensor, RFSignal, DummySensor
from app.services.presence.rf.rf_diagnostics import RFDiagnostics

log = logging.getLogger("markiii.presence")

POLL_INTERVAL_S   = 10.0   # How often to re-estimate presence
LOG_INTERVAL_TICKS = 6     # Log diagnostics every N polls (60s)


# ─────────────────────────────────────────────────────────────────
# Windows last-input time helper
# ─────────────────────────────────────────────────────────────────

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _windows_last_input_ms() -> int:
    """Return milliseconds since last keyboard or mouse event (Windows only)."""
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        return ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    except Exception:
        return 999_999   # assume idle if unavailable


# ─────────────────────────────────────────────────────────────────
# Presence Engine
# ─────────────────────────────────────────────────────────────────

class PresenceEngine:
    """
    Multi-source presence estimator.  Runs a background polling loop.

    Each poll:
      1. Read Windows last-input time → derive last_keyboard_s, last_mouse_s
      2. Read RF sensor → RFSignal
      3. Fuse all signals → PresenceEstimate
      4. Log to rf_events.json every 60s
    """

    def __init__(self, sensor: Optional[RFSensor] = None) -> None:
        self._sensor  : RFSensor        = sensor or DummySensor()
        self._fusion  : PresenceFusion  = PresenceFusion()
        self._diag    : RFDiagnostics   = RFDiagnostics()
        self._lock    : threading.Lock  = threading.Lock()

        self._running   = False
        self._thread: Optional[threading.Thread] = None
        self._tick      = 0

        # Externally updated timestamps (seconds since epoch)
        self._last_mic_s : float = 0.0
        self._last_app_s : float = 0.0

        # Current estimate (initialised to UNKNOWN)
        self._estimate: PresenceEstimate = PresenceEstimate.unknown()

        # Last RF signal (for status_dict)
        self._last_rf: Optional[RFSignal] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._poll_loop, daemon=True, name="presence-poll"
        )
        self._thread.start()
        log.info(
            "PresenceEngine started  sensor=%s  poll=%.0fs",
            self._sensor.name, POLL_INTERVAL_S,
        )

    def stop(self) -> None:
        self._running = False
        log.info("PresenceEngine stopped")

    # ------------------------------------------------------------------
    # External event signals (called from voice pipeline, tray, etc.)
    # ------------------------------------------------------------------

    def record_microphone(self) -> None:
        """Call when MARK receives an utterance (STT completed)."""
        with self._lock:
            self._last_mic_s = time.time()

    def record_activity(self) -> None:
        """Call on any user-driven app event (window change, tray click, etc.)."""
        with self._lock:
            self._last_app_s = time.time()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def estimate(self) -> PresenceEstimate:
        with self._lock:
            return self._estimate

    @property
    def state(self) -> str:
        return self.estimate.state

    @property
    def confidence(self) -> float:
        return self.estimate.confidence

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while self._running:
            self._poll_once()
            time.sleep(POLL_INTERVAL_S)

    def _poll_once(self) -> None:
        # ── Windows input timing ───────────────────────────────────
        idle_ms   = _windows_last_input_ms()
        idle_s    = idle_ms / 1000.0
        now       = time.time()
        last_input = now - idle_s

        # Split keyboard / mouse at this tier:
        # Windows GetLastInputInfo doesn't distinguish them, so we
        # use the same timestamp for both.  Phase 20 can add per-device
        # hooks if distinction is needed.
        last_keyboard_s = last_input
        last_mouse_s    = last_input

        with self._lock:
            last_mic_s = self._last_mic_s
            last_app_s = self._last_app_s

        # ── RF sensor ─────────────────────────────────────────────
        rf: Optional[RFSignal] = None
        try:
            if self._sensor.available:
                rf = self._sensor.get_signal()
        except Exception as e:
            log.debug("RF sensor error: %s", e)
        self._last_rf = rf

        # ── Fuse ──────────────────────────────────────────────────
        estimate = self._fusion.fuse(
            last_keyboard_s = last_keyboard_s,
            last_mouse_s    = last_mouse_s,
            last_mic_s      = last_mic_s,
            last_app_s      = last_app_s,
            rf              = rf,
        )

        with self._lock:
            old_state       = self._estimate.state
            self._estimate  = estimate

        # Log state changes immediately
        if estimate.state != old_state:
            log.info(
                "Presence: %s → %s  conf=%.0f%%  evidence=%s",
                old_state, estimate.state,
                estimate.confidence * 100,
                ", ".join(estimate.evidence),
            )

        # Periodic diagnostics write (every LOG_INTERVAL_TICKS polls)
        self._tick += 1
        if self._tick >= LOG_INTERVAL_TICKS:
            self._tick = 0
            self._diag.record(estimate, rf)
            log.debug(
                "Presence tick: state=%s conf=%.0f%% rf_motion=%s idle=%.0fs",
                estimate.state,
                estimate.confidence * 100,
                rf.movement_detected if rf else "N/A",
                idle_s,
            )

    # ------------------------------------------------------------------
    # Status API  (for REST endpoint / voice / tray)
    # ------------------------------------------------------------------

    def status_dict(self) -> dict:
        est = self.estimate
        rf  = self._last_rf
        return {
            "state":        est.state,
            "confidence":   est.confidence,
            "present":      est.present,
            "evidence":     est.evidence,
            "keyboard":     est.keyboard_score > 0.1,
            "mouse":        est.mouse_score    > 0.1,
            "microphone":   est.mic_score      > 0.1,
            "wifi_motion":  rf.movement_detected if rf else False,
            "rf_source":    rf.source           if rf else "none",
            "rf_zone":      rf.zone             if rf else None,
            "diagnostics":  self._diag.summary(),
        }

    def voice_summary(self) -> str:
        """Short natural-language presence report for TTS."""
        est = self.estimate
        if est.state == "active":
            return "You appear to be actively at your desk."
        if est.state == "working":
            return "You've been working — detected keyboard and mouse activity."
        if est.state == "present":
            rf = self._last_rf
            zone = f" in the {rf.zone}" if rf and rf.zone else ""
            return f"Movement detected{zone} — you appear to be present but not typing."
        if est.state == "idle":
            return "You seem idle — no recent input detected."
        if est.state == "away":
            return "You appear to be away — no presence signals detected."
        return "Presence state is currently unknown — insufficient sensor data."


# ─────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────

_engine: Optional[PresenceEngine] = None


def get_presence_engine() -> PresenceEngine:
    global _engine
    if _engine is None:
        _engine = PresenceEngine()
    return _engine


def start_presence_engine(sensor: Optional[RFSensor] = None) -> PresenceEngine:
    """Start the engine on first call; no-op on subsequent calls."""
    global _engine
    if _engine is None:
        _engine = PresenceEngine(sensor=sensor)
    if not _engine._running:
        _engine.start()
    return _engine
